// SPDX-License-Identifier: GPL-3.0-only
// RemotePilot Homebrew, a distinct application; not a resident service.
#include "platform.hpp"
#include "sha256.hpp"
#include "build_version.hpp"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <memory>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>

static constexpr uint64_t MaxFile=512ULL*1024*1024;
static constexpr size_t Chunk=65536;
#ifdef RPH_UPDATER
static const uint64_t OwnId=0x000400000F3D5300ULL;
static const bool Updater=true;
static std::string root="sdmc:/3ds/RemotePilotUpdater";
#else
static const uint64_t OwnId=0x000400000F3D5200ULL;
static const bool Updater=false;
static std::string root="sdmc:/3ds/RemotePilotHomebrew";
#endif
static const uint64_t CompanionId=0x000400000F3D5200ULL;
// Both titles use the already provisioned companion pairing, but independent
// staging/receipts. No new credential or arbitrary file-write command exists.
static std::string configRoot="sdmc:/3ds/RemotePilotHomebrew";
static std::string token;
static bool armed=false, launchPending=false, autonomous=false;
static uint64_t armedAt=0;
static FILE* file=nullptr;
static std::unique_ptr<sha256::Hasher> hasher;
static std::string afterHash;
static uint64_t ticks=0;
static uint64_t socketDeadline=0;
static std::vector<unsigned char> buffer(Chunk);
struct Job {
    std::string id, hash, title, state="idle", error="none";
    uint64_t size=0, done=0; unsigned version=0;
    bool autonomous=false, reviewed=false;
} job;

static bool hex(const std::string& s, size_t n) {
    return s.size()==n && s.find_first_not_of("0123456789abcdef")==std::string::npos;
}
static std::string idText(uint64_t id) { char s[17]; snprintf(s,sizeof(s),"%016llx",(unsigned long long)id); return s; }
static bool titleAllowed(const std::string& id) {
    return hex(id,16) && id.substr(0,8)=="00040000" && id!=idText(OwnId) &&
        (!Updater || id==idText(CompanionId));
}
static std::string bytesHex(const unsigned char* p,size_t n) {
    const char* d="0123456789abcdef"; std::string s;
    for(size_t i=0;i<n;i++){s+=d[p[i]>>4];s+=d[p[i]&15];}return s;
}
static std::string hmac(const std::string& message) {
    unsigned char inner[64],outer[64];
    memset(inner,0x36,64); memset(outer,0x5c,64);
    for(size_t i=0;i<32;i++) {
        unsigned char b=strtoul(token.substr(i*2,2).c_str(),nullptr,16);
        inner[i]^=b; outer[i]^=b;
    }
    sha256::Hasher first; first.update(inner,64);first.update(message.data(),message.size());
    std::string digest=first.finishHex(); unsigned char raw[32];
    for(size_t i=0;i<32;i++) raw[i]=strtoul(digest.substr(i*2,2).c_str(),nullptr,16);
    sha256::Hasher last;last.update(outer,64);last.update(raw,32);return last.finishHex();
}
static bool equal(const std::string& a,const std::string& b) {
    if(a.size()!=b.size())return false;
    unsigned char diff=0;
    for(size_t i=0;i<a.size();i++)diff|=a[i]^b[i];
    return diff==0;
}
static std::string jobJson() {
    return "{\"id\":\""+job.id+"\",\"state\":\""+job.state+"\",\"error\":\""+job.error+
        "\",\"done\":"+std::to_string(job.done)+",\"total\":"+std::to_string(job.size)+
        ",\"titleId\":\""+job.title+"\",\"version\":"+std::to_string(job.version)+
        ",\"approvalMode\":\""+(job.autonomous?"autonomous":"manual")+"\",\"reviewed\":"+(job.reviewed?"true":"false")+"}";
}
static bool receipt() {
    // Write-ahead receipt before AM mutation. A reboot never resumes automatically.
    std::string temporary=root+"/receipt.tmp", target=root+"/receipt.txt";
    FILE* f=fopen(temporary.c_str(),"wb");
    if(!f) return false;
    std::string data=job.id+" "+job.hash+" "+job.title+" "+job.state+" "+job.error+" "+
        std::to_string(job.size)+" "+std::to_string(job.done)+" "+std::to_string(job.version)+" "+
        (job.autonomous?"autonomous":"manual")+" "+(job.reviewed?"reviewed":"pending")+"\n";
    bool ok=fwrite(data.data(),1,data.size(),f)==data.size() && fflush(f)==0 && fsync(fileno(f))==0;
    if(fclose(f)!=0)ok=false;
    if(ok) { remove(target.c_str()); ok=rename(temporary.c_str(),target.c_str())==0; }
    return ok;
}
static void closeFile(){if(file){fclose(file);file=nullptr;}hasher.reset();}
static void fail(const std::string& error, const std::string& state="failed") {
    closeFile();job.state=state;job.error=error;job.reviewed=false;receipt();
}
static bool idleView() {
    return job.state=="idle"||job.state=="cancelled"||
        ((job.state=="failed"||job.state=="installed")&&job.reviewed);
}
static bool busy() { return job.state=="uploading"||job.state=="verifying"||job.state=="rechecking"||
    job.state=="awaiting-approval"||job.state=="installing"; }
static std::string error(const std::string& s) { return "{\"ok\":false,\"error\":\""+s+"\"}"; }
static std::string success() { return "{\"ok\":true,\"job\":"+jobJson()+"}"; }
static bool inventory(std::vector<Title>& titles) { return platform::titles(titles); }
static bool checkCia() {
    Title title{};uint64_t space=0;
    if(!platform::inspect(root+"/staged.cia",title,space)){fail("invalid-cia");return false;}
    if(idText(title.id)!=job.title||title.version!=job.version||!titleAllowed(job.title)) {
        fail("wrong-title-or-version");return false;
    }
    std::vector<Title> titles;
    if(!inventory(titles)){fail("inventory-failed");return false;}
    for(const auto& t:titles) if(t.id==title.id && t.version>=title.version) {
        fail("same-or-older-version");return false;
    }
    if(platform::freeSpace()<space+4*1024*1024ULL){fail("insufficient-install-space");return false;}
    return true;
}
static bool startHash(const std::string& next) {
    closeFile();file=fopen((root+"/staged.cia").c_str(),"rb");
    if(!file){fail("staged-file-unavailable");return false;}
    hasher.reset(new sha256::Hasher());afterHash=next;job.done=0;
    job.state=next=="installing"?"rechecking":"verifying";receipt();return true;
}
static void step() {
    if(job.state=="verifying"||job.state=="rechecking") {
        size_t got=fread(buffer.data(),1,Chunk,file);hasher->update(buffer.data(),got);job.done+=got;
        if(got)armedAt=platform::milliseconds();
        if(job.done>job.size||ferror(file)){fail("staged-read-failed");return;}
        if(got<Chunk) {
            std::string digest=hasher->finishHex(); closeFile();
            if(job.done!=job.size||digest!=job.hash){fail("sha256-mismatch");return;}
            if(!checkCia())return;
            if(afterHash=="installing") {
                // Log before any AM writes. Never delete/uninstall an old title.
                job.state="installing";job.done=0;
                if(!receipt()){fail("receipt-write-failed");return;}
                file=fopen((root+"/staged.cia").c_str(),"rb");
                if(!file||!platform::startInstall()){fail("install-start-failed");return;}
            } else {job.state="verified";receipt();}
        }
    } else if(job.state=="installing") {
        size_t got=fread(buffer.data(),1,Chunk,file);
        if(ferror(file)||(!got&&job.done<job.size)||got>job.size-job.done||
            (got&&!platform::writeInstall(job.done,buffer.data(),got))) {
            bool cancelled=platform::cancelInstall();
            fail(cancelled?"install-write-failed":"cancel-failed", "unknown");return;
        }
        job.done+=got;
        if(got)armedAt=platform::milliseconds();
        if(job.done==job.size) {
            closeFile();job.state="committing";receipt();
            if(!platform::finishInstall()){fail("install-finish-unconfirmed","unknown");return;}
            std::vector<Title> titles;
            if(!inventory(titles)){fail("post-install-inventory-failed","unknown");return;}
            bool found=false;
            for(const auto& t:titles)if(idText(t.id)==job.title&&t.version==job.version)found=true;
            if(!found){fail("installed-version-unconfirmed","unknown");return;}
            job.state="installed";receipt();
        }
    }
}
static std::string dispatch(const std::string& action,const std::string& body) {
    if(action=="status")return "{\"ok\":true,\"protocol\":1,\"resident\":false,\"armed\":"+
        std::string(armed?"true":"false")+",\"applicationTitleId\":\""+idText(OwnId)+
        "\",\"buildVersion\":"+std::to_string(RPH_BUILD_VERSION)+",\"updater\":"+(Updater?"true":"false")+
        ",\"readyForTransfer\":"+(armed&&idleView()?"true":"false")+
        ",\"autonomousSupported\":true,\"autonomousEnabled\":"+(armed&&autonomous?"true":"false")+
        ",\"updateTarget\":\""+(Updater?idText(CompanionId):std::string())+
        "\",\"capabilities\":[\"upload\",\"install\",\"titles\",\"launch\"],\"job\":"+jobJson()+"}";
    if(action=="titles") {
        if(!body.empty())return error("unexpected-body");
        std::vector<Title> titles;if(!inventory(titles))return error("inventory-failed");
        std::string result="{\"ok\":true,\"titles\":[";
        for(size_t i=0;i<titles.size();i++) {
            if(i)result+=",";
            result+="{\"titleId\":\""+idText(titles[i].id)+"\",\"version\":"+std::to_string(titles[i].version)+"}";
        }
        return result+"]}";
    }
    if(action=="job")return body==job.id?success():error("unknown-job");
    if(action=="cancel") {
        if(body!=job.id)return error("unknown-job");
        if(job.state=="installed"||job.state=="launching"||job.state=="unknown")return error("outcome-requires-inspection");
        bool wasInstall=job.state=="installing";
        bool stopped=platform::cancelInstall();closeFile();
        job.state=wasInstall?"unknown":stopped?"cancelled":"unknown";
        job.error=wasInstall?"install-cancelled-check-installed-title":stopped?"none":"cancel-failed";receipt();return success();
    }
    if(!armed)return error("arm-on-console-with-x");
    if(action=="begin") {
        if(busy()||job.state=="unknown")return error("job-already-active-or-unknown");
        Job next;std::istringstream args(body);std::string mode,extra;
        if(!(args>>next.id>>next.size>>next.hash>>next.title>>next.version)||!hex(next.id,32)||!hex(next.hash,64)||
           !titleAllowed(next.title)||!next.size||next.size>MaxFile||next.version>65535)return error("invalid-deployment");
        if(args>>mode) {
            if(mode!="autonomous"||(args>>extra))return error("invalid-deployment");
            if(!autonomous)return error("enable-autonomous-on-console-with-y");
            next.autonomous=true;
        }
        if(platform::freeSpace()<next.size+4*1024*1024ULL)return error("insufficient-upload-space");
        closeFile();file=fopen((root+"/staged.cia").c_str(),"wb");
        if(!file)return error("staging-open-failed");
        job=next;job.state="uploading";
        if(!receipt()){fail("receipt-write-failed");return error("receipt-write-failed");}
        armedAt=platform::milliseconds();
        return success();
    }
    if(action=="chunk") {
        size_t newline=body.find('\n');if(newline==std::string::npos||newline>64)return error("invalid-chunk");
        std::string id,extra;uint64_t offset=0;std::istringstream args(body.substr(0,newline));
        size_t length=body.size()-newline-1;
        if(!(args>>id>>offset)||(args>>extra)||id!=job.id||job.state!="uploading"||offset!=job.done||!length||
           length>Chunk||length>job.size-job.done)return error("out-of-order-chunk");
        if(fwrite(body.data()+newline+1,1,length,file)!=length){fail("staging-write-failed");return error("staging-write-failed");}
        job.done+=length;armedAt=platform::milliseconds();return success();
    }
    if(action=="verify") {
        if(body!=job.id||job.state!="uploading"||job.done!=job.size)return error("incomplete-upload");
        bool ok=fflush(file)==0;if(fclose(file)!=0)ok=false;file=nullptr;
        if(!ok){fail("staging-flush-failed");return error("staging-flush-failed");}
        startHash("verified");return success();
    }
    if(action=="install") {
        if(body!=job.id||job.state!="verified")return error("verify-before-install");
        armedAt=platform::milliseconds();
        if(job.autonomous&&autonomous) {
            if(!startHash("installing"))return error("staged-file-unavailable");
            return success();
        }
        job.autonomous=false; // revocation falls back to A; never silently installs.
        job.state="awaiting-approval";
        if(!receipt()){fail("receipt-write-failed");return error("receipt-write-failed");}
        return success();
    }
    if(action=="launch") {
        std::string id,title,extra;std::istringstream args(body);
        if(!(args>>id>>title)||(args>>extra)||!hex(id,32)||!titleAllowed(title)||busy()||job.state=="unknown")return error("invalid-launch");
        std::vector<Title> titles;if(!inventory(titles))return error("inventory-failed");
        bool found=false;for(const auto& t:titles)if(idText(t.id)==title)found=true;
        if(!found)return error("title-not-installed-on-sd");
        if(!platform::prepareLaunch(strtoull(title.c_str(),nullptr,16)))return error("launch-prepare-failed");
        job.id=id;job.title=title;job.state="launching";
        if(!receipt()){fail("receipt-write-failed");return error("receipt-write-failed");}
        launchPending=true;
        return "{\"ok\":true,\"state\":\"launching\",\"requestId\":\""+id+"\"}";
    }
    return error("unsupported-action");
}
static bool socketReady(int s,bool writing) {
    uint64_t now=platform::milliseconds();if(now>=socketDeadline)return false;
    uint64_t left=socketDeadline-now;timeval wait{long(left/1000),long((left%1000)*1000)};
    fd_set fds;FD_ZERO(&fds);FD_SET(s,&fds);
    return select(s+1,writing?nullptr:&fds,writing?&fds:nullptr,nullptr,&wait)>0;
}
static bool sendAll(int s,const std::string& data) {
    size_t done=0;while(done<data.size()){
        if(!socketReady(s,true))return false;
        int n=send(s,data.data()+done,data.size()-done,0);if(n<=0)return false;done+=n;}return true;
}
static bool readExact(int s,std::string& data,size_t size) {
    data.resize(size);size_t done=0;
    while(done<size){if(!socketReady(s,false))return false;
        int n=recv(s,&data[done],size-done,0);if(n<=0)return false;done+=n;}return true;
}
static bool readLine(int s,std::string& line) {
    for(size_t i=0;i<256;i++){char c; if(!socketReady(s,false)||recv(s,&c,1,0)!=1)return false;if(c=='\n')return true;
        if(c<32||c>126)return false;
        line+=c;}return false;
}
static void session(int s) {
    socketDeadline=platform::milliseconds()+4000;
    int noDelay=1;setsockopt(s,IPPROTO_TCP,TCP_NODELAY,&noDelay,sizeof(noDelay));
    fcntl(s,F_SETFL,fcntl(s,F_GETFL,0)|O_NONBLOCK);
    unsigned char random[32];if(!platform::random(random,sizeof(random)))return;
    std::string nonce=bytesHex(random,sizeof(random));
    if(!sendAll(s,"RPH1 CHALLENGE "+nonce+" "+hmac("server:"+nonce)+"\n"))return;
    std::string header,magic,id,action,digest,proof,extra;size_t length=0;
    if(!readLine(s,header))return;
    std::istringstream args(header);
    if(!(args>>magic>>id>>action>>length>>digest>>proof)||(args>>extra)||magic!="RPH1"||!hex(id,16)||
       !hex(digest,64)||!hex(proof,64)||length>Chunk+128||action.size()>16)return;
    std::string message="request:"+nonce+":"+id+":"+action+":"+std::to_string(length)+":"+digest;
    if(!equal(proof,hmac(message)))return;
    std::string body;if(!readExact(s,body,length)||sha256::ofString(body)!=digest)return;
    std::string result=dispatch(action,body);digest=sha256::ofString(result);
    message="response:"+nonce+":"+id+":"+std::to_string(result.size())+":"+digest;
    // SD flush/receipt work may consume the request's socket deadline. Give the
    // bounded acknowledgement its own window after the operation completes.
    socketDeadline=platform::milliseconds()+4000;
    bool sent=sendAll(s,"RPH1 "+id+" "+std::to_string(result.size())+" "+digest+" "+hmac(message)+"\n"+result);
    if(sent)shutdown(s,SHUT_WR);
    if(launchPending) {
        launchPending=false;
        // The client must never retry if the acknowledgement is lost.
        if(!sent){fail("launch-acknowledgement-lost","unknown");return;}
        if(!platform::launch())fail("application-jump-failed");
    }
}
int main(int argc,char** argv) {
#ifndef __3DS__
    if(argc>1)root=argv[1];
    configRoot=root; // desktop tests have isolated synthetic pairing only.
    if(argc>2)configRoot=argv[2];
#else
    (void)argc; (void)argv; // production SD paths cannot be redirected by launch arguments.
#endif
    bool ready=platform::init();
#ifndef __3DS__
    if(!ready)return 2;
#endif
    mkdir(root.c_str(),0777);
    std::ifstream config(configRoot+"/remote-pilot-homebrew.cfg");std::string entry;unsigned port=38765;
    while(std::getline(config,entry)) {
        if(!entry.empty()&&entry.back()=='\r')entry.pop_back();
        if(entry.find("token=")==0)token=entry.substr(6);
        if(entry.find("port=")==0)port=strtoul(entry.substr(5).c_str(),nullptr,10);
    }
    // A leftover temporary receipt takes precedence over an older completed
    // receipt. Never infer a safe outcome from partial write-ahead state.
    std::ifstream previous(root+"/receipt.tmp");
    const bool uncommitted=previous.is_open();
    if(!uncommitted)previous.open(root+"/receipt.txt");
    if(previous.is_open()) {
        Job restored;
        previous.seekg(0,std::ios::end);const auto receiptSize=previous.tellg();previous.seekg(0);
        bool valid=receiptSize>0&&receiptSize<=1024;
        valid=valid&&bool(previous>>restored.id>>restored.hash>>restored.title>>restored.state>>restored.error>>restored.size>>restored.done>>restored.version);
        valid=valid&&hex(restored.id,32)&&hex(restored.hash,64)&&hex(restored.title,16)&&
            restored.size<=MaxFile&&restored.done<=restored.size&&restored.version<=65535&&restored.state.size()<=24&&
            !restored.error.empty()&&restored.error.size()<=64&&restored.error.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_-")==std::string::npos;
        std::string mode,review,extra;
        if(valid&&(previous>>mode)) {
            valid=valid&&(mode=="manual"||mode=="autonomous");restored.autonomous=mode=="autonomous";
            if(previous>>review) {
                valid=valid&&(review=="reviewed"||review=="pending");restored.reviewed=review=="reviewed";
                if(previous>>extra)valid=false;
            }
        }
        if(valid) {
            job=restored;
            if(uncommitted) {job.state="unknown";job.error="uncommitted-receipt";}
            else if(job.state!="installed"&&job.state!="cancelled"&&job.state!="failed")job.state="unknown";
            if(job.state=="failed"&&job.error=="owner-reviewed-unknown-outcome")job.reviewed=true;
            if(job.state=="unknown")job.reviewed=false;
        } else {
            // A valid, non-installable tombstone lets the owner acknowledge a
            // corrupt receipt while retaining the unknown-outcome interlock.
            job=Job();job.id=std::string(32,'0');job.hash=std::string(64,'0');job.title=idText(OwnId);
            job.state="unknown";job.error="invalid-receipt";
        }
    }
    // FS cannot replace a receipt while the startup reader still owns its
    // handle. Release it before the first B acknowledgement or deployment.
    previous.close();
    int listener=-1;
    if(ready&&hex(token,64)&&port>=1024&&port<=65535) {
        listener=socket(AF_INET,SOCK_STREAM,0);int one=1;
        setsockopt(listener,SOL_SOCKET,SO_REUSEADDR,&one,sizeof(one));
        sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(port);address.sin_addr.s_addr=INADDR_ANY;
        if(bind(listener,reinterpret_cast<sockaddr*>(&address),sizeof(address))<0||listen(listener,4)<0){close(listener);listener=-1;}
    }
    while(platform::running()) {
        ticks++;unsigned keys=platform::keys();
        if(keys&8)break;
        if(keys&4) {
            armed=!armed;armedAt=platform::milliseconds();
            if(!armed)autonomous=false;
            if(!armed&&busy())dispatch("cancel",job.id);
        }
        if(armed&&platform::milliseconds()-armedAt>15*60*1000ULL) {
            autonomous=false;
            if(!busy())armed=false;
        }
        if(keys&16) {
            if(autonomous) {
                autonomous=false;
                if(job.autonomous&&(busy()||job.state=="verified")&&job.state!="installing") {
                    job.autonomous=false;
                    if(job.state=="rechecking") {closeFile();job.state="awaiting-approval";}
                    receipt();
                }
            } else if(armed&&!busy()&&job.state!="unknown") {
                autonomous=true;armedAt=platform::milliseconds();
            }
        }
        if((keys&1)&&job.state=="awaiting-approval")startHash("installing");
        if(keys&2) {
            if(job.state=="unknown") {job.state="failed";job.error="owner-reviewed-unknown-outcome";job.reviewed=true;if(!receipt())fail("receipt-write-failed");}
            else if(busy()||job.state=="verified")dispatch("cancel",job.id);
            else if(job.state=="failed"||job.state=="installed") {job.reviewed=true;if(!receipt())fail("receipt-write-failed");}
        }
        step();
        if(listener>=0) {
            fd_set read;FD_ZERO(&read);FD_SET(listener,&read);timeval wait{0,0};
            if(select(listener+1,&read,nullptr,nullptr,&wait)>0) {
                int client=accept(listener,nullptr,nullptr);if(client>=0){session(client);close(client);}
            }
        }
        if(ticks%15==1) {
            platform::Dashboard ui;
            ui.recovery=Updater;ui.listening=listener>=0;ui.armed=armed;ui.autonomous=autonomous;ui.active=busy()||job.state=="unknown";
            const bool idle=idleView();
            ui.build=RPH_BUILD_VERSION;
            if(!idle){ui.version=job.version;ui.done=job.done;ui.total=job.size;ui.hash=job.hash;}
            ui.address=platform::networkAddress()+":"+std::to_string(port);
            if(!idle&&!job.id.empty())ui.target=job.title=="000400000f3d5000"?"MORROWIND GUIDEBOOK":job.title==idText(CompanionId)?"REMOTEPILOT":job.title=="000400000f3d5300"?"RECOVERY UPDATER":"APPLICATION UPDATE";
            ui.phase="READY FOR TRANSFER";
            if(idle){} // Historical receipts remain available to the paired PC.
            else if(job.state=="uploading")ui.phase="RECEIVING FILE";
            else if(job.state=="verifying")ui.phase="CHECKING FILE";
            else if(job.state=="verified")ui.phase="FILE CHECKED";
            else if(job.state=="awaiting-approval")ui.phase="AWAITING APPROVAL";
            else if(job.state=="rechecking")ui.phase="RECHECKING FILE";
            else if(job.state=="installing")ui.phase="INSTALLING";
            else if(job.state=="committing")ui.phase="FINISHING INSTALL";
            else if(job.state=="installed")ui.phase="INSTALL COMPLETE";
            else if(job.state=="cancelled")ui.phase="TRANSFER CANCELLED";
            else if(job.state=="failed")ui.phase="TRANSFER STOPPED";
            else if(job.state=="unknown")ui.phase="CHECK PC OUTCOME";
            else if(job.state=="launching")ui.phase="OPENING NEXT APP";
            ui.instruction="No button press needed. Keep this app and the lid open.";
            ui.next=job.autonomous?"Next: check file, then automatic install.":"Next: file check, then A approval.";
            if(job.state=="unknown") {
                ui.prompt=platform::UserPrompt::review;
                ui.instruction="Inspect title and version on the PC first. Then B acknowledges it.";
                ui.next="No automatic retry of an unknown result.";
            } else if((job.state=="failed"||job.state=="installed")&&!job.reviewed) {
                ui.prompt=platform::UserPrompt::review;
                ui.instruction=job.state=="failed"?"Read the result on the PC. B acknowledges it and returns to ready.":"Install complete. B returns to ready; launch the app from the PC.";
                ui.next="The result stays in transfer history.";
            } else if(job.state=="awaiting-approval") {
                ui.prompt=platform::UserPrompt::approve;
                ui.instruction="Approve the title, version and hash below. B rejects this update.";
                ui.next="After A: recheck, install and confirm.";
            } else if(!armed&&!busy()) {
                ui.prompt=platform::UserPrompt::arm;
                ui.instruction="Press X once to arm this session. Keep the app open.";
                ui.next="Next: use the PC to send an update.";
            } else if(job.state=="rechecking"||job.state=="installing"||job.state=="committing") {
                ui.instruction=job.autonomous?"Automatic install enabled for this job. No A press needed.":"Installation running. Keep the app and lid open.";
                ui.next="Next: PC confirms the installed version.";
            } else if(job.state=="installed"&&!idle) {
                ui.instruction=Updater?"On the PC, choose Reopen companion.":"Installation confirmed. Continue on the PC.";
                ui.next="Use the PC to open the updated app.";
            } else if(idle) {
                ui.instruction=Updater?"On the PC, send the main companion update.":"On the PC, select an update to send.";
                ui.next=Updater?"Only RemotePilot companion CIAs here.":"CIA apps now. Y: optional auto mode.";
            }
            if(listener<0) {
                ui.prompt=platform::UserPrompt::none;
                ui.instruction="Not listening. Check pairing and setup on the PC.";
                ui.next="Next: finish setup before sending files.";
            }
            platform::dashboard(ui);
        }
    }
    if(job.state=="installing"){platform::cancelInstall();fail("application-closed-during-install","unknown");}
    else if(busy())fail("application-closed","cancelled");
    closeFile();if(listener>=0)close(listener);platform::exit();return 0;
}
