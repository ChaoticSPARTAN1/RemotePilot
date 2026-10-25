// SPDX-License-Identifier: GPL-3.0-only
// Included after the authenticated socket helpers in main.cpp.
namespace game_data {
struct State {
    std::string id,hash,target,path,temporary,state="idle",error="none";
    uint64_t total=0,done=0;
    FILE* file=nullptr;
    bool existing=false;
    std::unique_ptr<sha256::Hasher> digest;
} data;
static std::string lower(std::string s) { for(char& c:s)if(c>='A'&&c<='Z')c+=32;return s; }
static bool safePath(const std::string& path,bool target=false) {
    if(path.empty()||path.size()>(target?128:224)||path.front()=='/'||path.back()=='/')return false;
    std::istringstream parts(path);std::string part;unsigned count=0;
    while(std::getline(parts,part,'/')) {
        if(part.empty()||part=="."||part==".."||part.front()=='.'||part.back()=='.'||part.back()==' '||part.size()>96)return false;
        for(unsigned char c:part)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.'||c==' '))return false;
        std::string name=lower(part),stem=name.substr(0,name.find('.'));
        if(stem=="con"||stem=="prn"||stem=="aux"||stem=="nul"||
           (stem.size()==4&&(stem.substr(0,3)=="com"||stem.substr(0,3)=="lpt")&&stem[3]>='1'&&stem[3]<='9'))return false;
        if(name=="save"||name=="saves"||name=="savegame"||name=="local"||name=="private"||name=="luma"||name=="boot9strap"||
           name=="gm9"||name=="nintendo 3ds"||name=="dcim"||name=="cias"||name=="remotepilothomebrew"||name=="remotepilotupdater"||
           name=="token"||name=="pairing.json"||name=="credentials.json"||name=="secrets.json"||name.find("remote-pilot")!=std::string::npos)return false;
        count++;
    }
    std::string name=lower(path);
    if(target&&name.compare(0,4,"3ds/")==0) {
        size_t slash=name.find('/',4);
        if(slash==std::string::npos||name.substr(slash)!="/data")return false;
    } else if(target&&name=="3ds")return false;
    if(!target) {
        size_t dot=name.find_last_of('.');std::string ext=dot==std::string::npos?"":name.substr(dot);
        if(ext==".cia"||ext==".3dsx"||ext==".firm"||ext==".exe"||ext==".dll"||ext==".ps1"||ext==".bat"||ext==".cmd"||ext==".key"||ext==".pem")return false;
    }
    return count<=16;
}
static std::string base() {
#ifdef __3DS__
    return "sdmc:/";
#else
    return root+"/test-game-data/";
#endif
}
static bool exists(const std::string& path) { struct stat st{};return lstat(path.c_str(),&st)==0; }
static bool parents(const std::string& path) {
#ifndef __3DS__
    mkdir((root+"/test-game-data").c_str(),0777);
#endif
    for(size_t at=base().size();(at=path.find('/',at))!=std::string::npos;at++) {
        std::string part=path.substr(0,at);struct stat st{};
        if(lstat(part.c_str(),&st)==0) {if(!S_ISDIR(st.st_mode))return false;}
        else if(mkdir(part.c_str(),0777)!=0)return false;
    }
    return true;
}
static std::string json() {
    return "{\"id\":\""+data.id+"\",\"state\":\""+data.state+"\",\"error\":\""+data.error+
      "\",\"path\":\""+data.path+"\",\"targetRoot\":\""+data.target+"\",\"sha256\":\""+data.hash+
      "\",\"done\":"+std::to_string(data.done)+",\"total\":"+std::to_string(data.total)+"}";
}
static bool busy() {return data.state=="receiving"||data.state=="checking";}
static void close() {if(data.file){fclose(data.file);data.file=nullptr;}data.digest.reset();}
static bool receipt() {
    FILE* f=fopen((root+"/data-receipt.txt").c_str(),"wb");if(!f)return false;
    std::string value=json()+"\n";
    bool ok=fwrite(value.data(),1,value.size(),f)==value.size()&&fflush(f)==0&&fsync(fileno(f))==0;
    return fclose(f)==0&&ok;
}
static std::string fail(const std::string& why) {close();data.state="failed";data.error=why;receipt();return error(why);}
static std::string success() {return "{\"ok\":true,\"dataJob\":"+json()+"}";}
static void step() {
    if(data.state!="checking")return;
    for(unsigned n=0;n<8;n++) {
        size_t got=fread(buffer.data(),1,Chunk,data.file);
        data.digest->update(buffer.data(),got);data.done+=got;
        if(got)armedAt=platform::milliseconds();
        if(data.done>data.total||ferror(data.file)){fail("data-read-failed");return;}
        if(got<Chunk) {
            std::string hash=data.digest->finishHex();close();
            if(data.done!=data.total||hash!=data.hash){fail(data.existing?"existing-data-differs":"data-sha256-mismatch");return;}
            if(!data.existing) {
                std::string target=base()+data.target+"/"+data.path;
                if(exists(target)||rename(data.temporary.c_str(),target.c_str())!=0){fail("data-commit-failed");return;}
            }
            data.state=data.existing?"present":"complete";
            if(!receipt())fail("data-receipt-failed");
            return;
        }
    }
}
static std::string dispatch(const std::string& action,const std::string& body) {
    if(Updater)return error("data-not-supported-in-recovery");
    if(action=="data-status")return body==data.id||body.empty()?success():error("unknown-data-job");
    if(action=="data-cancel") {
        if(body!=data.id)return error("unknown-data-job");
        close();data.state="cancelled";receipt();return success();
    }
    if(!armed)return error("arm-on-console-with-x");
    if(action=="data-begin") {
        if(::busy()||job.state=="unknown")return error("job-already-active-or-unknown");
        State next;std::istringstream lines(body);std::string header,extra;
        if(!std::getline(lines,header)||!std::getline(lines,next.target)||!std::getline(lines,next.path)||std::getline(lines,extra))return error("invalid-data-request");
        std::istringstream args(header);
        if(!(args>>next.id>>next.total>>next.hash)||(args>>extra)||!hex(next.id,32)||!hex(next.hash,64)||
           next.total>0x7FFFFFFFULL||!safePath(next.target,true)||!safePath(next.path))return error("invalid-data-request");
        std::string target=base()+next.target+"/"+next.path;
        next.existing=exists(target);next.temporary=target+".rph-"+next.id+".part";
        if(!next.existing&&platform::freeSpace()<next.total+4*1024*1024ULL)return error("insufficient-data-space");
        if(!parents(target)||(!next.existing&&exists(next.temporary)))return error("data-directory-unavailable");
        if(next.existing) {
            struct stat st{};if(lstat(target.c_str(),&st)||!S_ISREG(st.st_mode)||uint64_t(st.st_size)!=next.total)return error("existing-data-differs");
        }
        close();data=std::move(next);
        if(data.existing)data.file=fopen(target.c_str(),"rb");
        else {
            int fd=open(data.temporary.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);
            if(fd>=0){data.file=fdopen(fd,"wb");if(!data.file)::close(fd);}
        }
        if(!data.file)return fail("data-open-failed");
        data.state=data.existing?"checking":"receiving";
        if(data.existing)data.digest.reset(new sha256::Hasher());
        armedAt=platform::milliseconds();if(!receipt())return fail("data-receipt-failed");
        return success();
    }
    if(action=="data-end") {
        if(body!=data.id||data.state!="receiving"||data.done!=data.total)return error("incomplete-data");
        bool ok=fflush(data.file)==0&&fsync(fileno(data.file))==0;close();
        if(!ok)return fail("data-flush-failed");
        data.file=fopen(data.temporary.c_str(),"rb");if(!data.file)return fail("data-open-failed");
        data.digest.reset(new sha256::Hasher());data.done=0;data.state="checking";armedAt=platform::milliseconds();receipt();
        return success();
    }
    return error("unsupported-data-action");
}
static bool streamReady(const std::string& body,uint64_t& count) {
    std::string id,extra;uint64_t offset=0;std::istringstream args(body);
    return !Updater&&armed&&data.state=="receiving"&&(args>>id>>offset>>count)&&!(args>>extra)&&id==data.id&&
        offset==data.done&&count&&count<=4*1024*1024&&count<=data.total-data.done;
}
static std::string stream(int socket,const std::string& nonce,uint64_t count) {
    while(count) {
        socketDeadline=platform::milliseconds()+10000;
        size_t n=std::min<uint64_t>(Chunk,count);std::string proof,body;
        if(!readExact(socket,proof,64)||!readExact(socket,body,n))return fail("data-stream-interrupted");
        std::string message="data:"+nonce+":"+data.id+":"+std::to_string(data.done)+":"+std::to_string(n)+":"+sha256::ofString(body);
        if(!equal(proof,hmac(message)))return fail("data-frame-authentication-failed");
        if(fwrite(body.data(),1,n,data.file)!=n)return fail("data-write-failed");
        data.done+=n;count-=n;armedAt=platform::milliseconds();
        unsigned keys=platform::keys();
        if((keys&14)||!platform::running()) {if(keys&4)armed=false;close();data.state="cancelled";receipt();return error("data-cancelled-on-console");}
        if(data.done%(1024*1024)==0) {
            platform::Dashboard ui;ui.listening=true;ui.armed=armed;ui.active=true;ui.build=RPH_BUILD_VERSION;
            ui.done=data.done;ui.total=data.total;ui.phase="FAST GAME DATA";ui.target=data.path;
            ui.instruction="Receiving checked game assets. B stops this file.";ui.next="SHA-256 check before committing each file.";
            platform::dashboard(ui);
        }
    }
    if(fflush(data.file)!=0||fsync(fileno(data.file))!=0)return fail("data-flush-failed");
    if(!receipt())return fail("data-receipt-failed");
    return success();
}
}
static bool dataBusy(){return game_data::busy();}
static void dataStep(){game_data::step();}
static std::string dataDispatch(const std::string& action,const std::string& body){return game_data::dispatch(action,body);}
static std::string dataStatus(){return game_data::json();}
