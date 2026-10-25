// SPDX-License-Identifier: GPL-3.0-only
// Read-only diagnostic catalog. Never accepts a filesystem path from the PC.
#include <dirent.h>
namespace diagnostics {
static constexpr size_t Max=4*1024*1024;
struct Entry { std::string id,path,kind; uint64_t size; };
static std::vector<unsigned char> snapshot;
static std::string snapshotId;
static std::string base() {
#ifdef __3DS__
    return "sdmc:/";
#else
    return root+"/test-game-data/";
#endif
}
static bool safeFile(const std::string& relative,struct stat& st) {
    std::string path=base();size_t at=0;
    while(at<relative.size()) {
        size_t end=relative.find('/',at);bool last=end==std::string::npos;
        path+=relative.substr(at,last?std::string::npos:end-at);
        if(lstat(path.c_str(),&st)!=0||(!last&&!S_ISDIR(st.st_mode))||(last&&!S_ISREG(st.st_mode)))return false;
        if(last)break;
        path+='/';at=end+1;
    }
    return st.st_size>=0&&uint64_t(st.st_size)<=Max;
}
static bool nameSafe(const std::string& name) {
    if(name.empty()||name.size()>96||name[0]=='.')return false;
    for(unsigned char c:name)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.'))return false;
    return true;
}
static std::vector<Entry> catalog() {
    std::vector<Entry> entries;
    auto add=[&](const std::string& path,const std::string& kind) {
        struct stat st{};if(entries.size()>=128||!safeFile(path,st))return;
        sha256::Hasher hash;hash.update(path.data(),path.size());
        entries.push_back({hash.finishHex().substr(0,32),path,kind,uint64_t(st.st_size)});
    };
    add("doom3/log.txt","text");add("doom3/stack-near-limit.bin","dump");
    add("3ds/mw3ds/watchdog.txt","text");add("3ds/mw3ds/log.txt","text");add("3ds/mw3ds/crash.txt","text");
    // Only dedicated crash/screenshot directories; never DCIM, saves or pairing.
    for(const char* folder:{"luma/dumps/arm11","luma/dumps/arm9","luma/screenshots","doom3/screenshots","3ds/mw3ds/screenshots","3ds/mw3ds/bug-it","3ds/RemotePilotHomebrew/bug-images"}) {
        struct stat st{};std::string relative(folder),prefix=relative+"/";
        // Check directory ancestors using a known dummy final component below.
        std::string path=base();bool valid=true;std::istringstream parts(relative);std::string part;
        while(std::getline(parts,part,'/')){path+=part;if(lstat(path.c_str(),&st)!=0||!S_ISDIR(st.st_mode)){valid=false;break;}path+='/';}
        if(!valid)continue;
        DIR* dir=opendir((base()+relative).c_str());if(!dir)continue;
        unsigned scanned=0;dirent* item;
        std::vector<std::string> names;
        while((item=readdir(dir))&&scanned++<4096){std::string name(item->d_name);if(nameSafe(name))names.push_back(name);}
        closedir(dir);std::sort(names.rbegin(),names.rend());
        unsigned added=0;
        for(const auto& name:names) {
            size_t dot=name.find_last_of('.');if(dot==std::string::npos)continue;
            std::string ext=name.substr(dot);for(char& c:ext)if(c>='A'&&c<='Z')c+=32;
            bool bugLog=relative=="3ds/mw3ds/bug-it"&&ext==".txt"&&(name=="crash.txt"||name.compare(0,5,"logs-")==0);
            if(bugLog){add(prefix+name,"text");if(++added>=24)break;continue;}
            bool dumps=relative.compare(0,11,"luma/dumps/")==0;
            if(dumps?(ext==".dmp"&&name.compare(0,11,"crash_dump_")==0):(ext==".png"||ext==".bmp"||ext==".jpg"||ext==".jpeg")) {
                add(prefix+name,dumps?"dump":"image");if(++added>=24)break;
            }
        }
    }
    return entries;
}
static std::string dispatch(const std::string& action,const std::string& body) {
    if(Updater)return error("diagnostics-not-supported-in-recovery");
    if(!armed)return error("arm-on-console-with-x");
    if(::busy()||job.state=="unknown")return error("finish-deployment-before-diagnostics");
    armedAt=platform::milliseconds();
    if(action=="diag-close") {snapshot.clear();snapshot.shrink_to_fit();snapshotId.clear();return "{\"ok\":true}";}
    if(action=="diag-list") {
        if(!body.empty())return error("unexpected-body");
        std::string out="{\"ok\":true,\"files\":[";bool first=true;
        for(const auto& e:catalog()) {
            if(!first)out+=",";
            first=false;out+="{\"id\":\""+e.id+"\",\"path\":\""+e.path+"\",\"kind\":\""+e.kind+"\",\"size\":"+std::to_string(e.size)+"}";
        }
        return out+"]}";
    }
    if(action=="diag-open") {
        snapshot.clear();snapshotId.clear();
        if(!hex(body,32))return error("invalid-diagnostic-id");
        for(const auto& e:catalog())if(e.id==body) {
            struct stat st{};if(!safeFile(e.path,st))return error("diagnostic-file-unavailable");
            FILE* f=fopen((base()+e.path).c_str(),"rb");if(!f)return error("diagnostic-open-failed");
            snapshot.resize(e.size);size_t n=fread(snapshot.data(),1,snapshot.size(),f);
            int extra=fgetc(f);bool ok=n==e.size&&!ferror(f)&&extra==EOF;fclose(f);
            if(!ok){snapshot.clear();return error("diagnostic-changed-during-read");}
            sha256::Hasher hash;hash.update(snapshot.data(),snapshot.size());snapshotId=hash.finishHex();
            return "{\"ok\":true,\"sha256\":\""+snapshotId+"\",\"size\":"+std::to_string(snapshot.size())+"}";
        }
        return error("diagnostic-file-unavailable");
    }
    if(action=="diag-read") {
        std::istringstream args(body);std::string id,extra;uint64_t offset=0,count=0;
        if(!(args>>id>>offset>>count)||(args>>extra)||id!=snapshotId||!hex(id,64)||count>32768||!count||offset>snapshot.size()||count>snapshot.size()-offset)return error("invalid-diagnostic-read");
        return "{\"ok\":true,\"offset\":"+std::to_string(offset)+",\"hex\":\""+bytesHex(snapshot.data()+offset,count)+"\"}";
    }
    return error("unsupported-action");
}
}
