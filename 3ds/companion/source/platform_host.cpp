// SPDX-License-Identifier: GPL-3.0-only
// Explicit desktop simulation. Never included in the ARM build.
#include "platform.hpp"
#include <fstream>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
#include <fcntl.h>
#include <sys/statvfs.h>
#include <vector>
#include <chrono>
#include <thread>
namespace platform {
static std::vector<Title> installed;
static Title pending{};
static std::string stateRoot;
static bool installing=false;
static uint64_t written=0;
static std::string titleStore;
static void readTitles(){
    if(titleStore.empty())return;
    installed.clear();std::ifstream f(titleStore);uint64_t id;unsigned version;
    while(f>>std::hex>>id>>std::dec>>version)installed.push_back({id,uint16_t(version)});
}
bool init(){const char* path=getenv("RPH_TEST_ROOT");if(!path)return false;stateRoot=path;
    const char* store=getenv("RPH_TEST_TITLE_STORE");if(store)titleStore=store;
    return !stateRoot.empty();}
void exit(){}
bool running(){std::this_thread::sleep_for(std::chrono::milliseconds(1));return true;}
uint64_t milliseconds(){
    uint64_t offset=0;std::ifstream clock(stateRoot+"/test-clock-offset");clock>>offset;
    return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count()+offset;
}
std::string networkAddress(){return "desktop simulation";}
unsigned keys(){
    std::ifstream f(stateRoot+"/test-key");unsigned k=0;f>>k;
    if(k)remove((stateRoot+"/test-key").c_str());
    return k;
}
bool random(void* p,size_t n){int f=open("/dev/urandom",O_RDONLY);if(f<0)return false;ssize_t got=read(f,p,n);close(f);return got==ssize_t(n);}
bool titles(std::vector<Title>& result){readTitles();result=installed;return true;}
uint64_t freeSpace(){return 4ULL*1024*1024*1024;}
static uint32_t le(const unsigned char* p){return p[0]|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;}
bool inspect(const std::string& path,Title& title,uint64_t& required){
    std::ifstream f(path,std::ios::binary);unsigned char h[32];if(!f.read((char*)h,32)||le(h)!=0x2020)return false;
    auto align=[](uint64_t n){return (n+63)&~63ULL;};
    uint64_t tmd=align(align(align(0x2020)+le(h+8))+le(h+12));
    f.seekg(tmd+0x140);unsigned char body[0xc4];if(!f.read((char*)body,sizeof(body)))return false;
    uint64_t id=0;for(int i=0;i<8;i++)id=(id<<8)|body[0x4c+i];
    title={id,uint16_t((body[0x9c]<<8)|body[0x9d])};pending=title;required=1024;return true;
}
bool startInstall(){installing=true;written=0;return true;}
bool writeInstall(uint64_t offset,const void*,size_t count){if(!installing||written!=offset)return false;written+=count;return true;}
bool finishInstall(){if(!installing)return false;installing=false;
    if(std::ifstream(stateRoot+"/test-finish-fail").good())return false;
    readTitles();bool found=false;
    for(auto& t:installed)if(t.id==pending.id){t=pending;found=true;break;}
    if(!found)installed.push_back(pending);
    if(!titleStore.empty()){
        std::ofstream f(titleStore);for(const auto& t:installed)f<<std::hex<<t.id<<" "<<std::dec<<t.version<<"\n";
        if(!f.good())return false;
    }
    return true;}
bool cancelInstall(){installing=false;return true;}
bool prepareLaunch(uint64_t){return true;}
bool launch(){return false;} // desktop cannot jump; expose actual failure receipt.
void display(const std::string&,const std::string&,UserPrompt){}
void dashboard(const Dashboard& ui){
    std::ofstream out(stateRoot+"/test-dashboard.txt");
    out<<ui.phase<<'\n'<<ui.target<<'\n'<<ui.total<<'\n'<<ui.instruction<<'\n';
}
}
