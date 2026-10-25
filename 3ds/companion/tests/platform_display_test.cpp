// Exercises production platform.cpp with rotating guarded framebuffers.
// This checks memory ownership/presentation, not physical LCD appearance.
#include <cstddef>
#include "3ds.h"
#include "platform.hpp"
#include "screen_banner_bin.h"
#include <array>
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <vector>
unsigned char screen_banner_bin[40000]={0x11,0x22};
const unsigned int screen_banner_bin_size=sizeof(screen_banner_bin);
static constexpr u16 Guard=0xdead, VisibleMark=0xa55a;
static std::vector<u16> pixels[2][2];
static unsigned current[2];
static bool doubled[2];
static unsigned waits=0, swaps=0, flushes=0;
static bool chainloaderSet=false;
static constexpr u64 launchTarget=0x000400000f3d5300ULL;
static u8 testFont[256*8];
static std::vector<u16> before[2];
static size_t count(unsigned screen){return (screen==GFX_TOP?400:320)*240;}
static u16* data(unsigned screen,unsigned id){return pixels[screen][id].data()+1;}
void gfxInit(GSPGPU_FramebufferFormat a,GSPGPU_FramebufferFormat b,bool vram){
    assert(a==GSP_RGB565_OES&&b==GSP_RGB565_OES&&!vram);
    for(unsigned s=0;s<2;s++)for(unsigned i=0;i<2;i++)pixels[s][i].assign(count(s)+2,Guard);
}
void gfxSetDoubleBuffering(gfxScreen_t s,bool enabled){doubled[s]=enabled;}
u8* gfxGetFramebuffer(gfxScreen_t s,gfx3dSide_t,u16*,u16*){
    return reinterpret_cast<u8*>(data(s,current[s]^(doubled[s]?1:0)));
}
PrintConsole* consoleInit(gfxScreen_t s,PrintConsole* c){
    gfxSetDoubleBuffering(s,false); c->frameBuffer=reinterpret_cast<u16*>(gfxGetFramebuffer(s,GFX_LEFT,nullptr,nullptr));
    std::fill(std::begin(testFont),std::end(testFont),0xff);c->font={testFont,0,256};return c;
}
PrintConsole* consoleSelect(PrintConsole* c){return c;}
void gfxFlushBuffers(){
    flushes++;
    for(unsigned s=0;s<2;s++)assert(std::equal(before[s].begin(),before[s].end(),pixels[s][current[s]].begin()));
}
void gfxSwapBuffers(){
    assert(flushes==swaps+1);swaps++;
    for(unsigned s=0;s<2;s++){assert(doubled[s]);current[s]^=1;}
}
void gspWaitForVBlank(){waits++;}
Result amInit(){return 0;} Result psInit(){return 0;} Result socInit(u32*,u32){return 0;}
void socExit(){} void amExit(){} void psExit(){} void gfxExit(){}
Result AM_CancelCIAInstall(Handle){return 0;}
// Unused service entry points fail loudly if this graphics-only test reaches one.
bool aptMainLoop(){std::abort();} uint64_t svcGetSystemTick(){return 0;}
void hidScanInput(){std::abort();} u32 hidKeysDown(){std::abort();}
Result PS_GenerateRandomBytes(void*,size_t){std::abort();}
Result AM_GetTitleCount(int,u32*){std::abort();}
Result AM_GetTitleList(u32*,int,u32,u64*){std::abort();}
Result AM_GetTitleInfo(int media,u32 count,u64* id,AM_TitleInfo* info){
    assert(media==MEDIATYPE_SD&&count==1);
    if(*id!=launchTarget)return -1;
    *info={*id,9};return 0;
}
FS_Path fsMakePath(int,const char*){std::abort();}
Result FSUSER_OpenFileDirectly(Handle*,int,FS_Path,FS_Path,int,int){std::abort();}
Result AM_GetCiaFileInfo(int,AM_TitleInfo*,Handle){std::abort();}
Result AM_GetCiaRequiredSpace(u64*,int,Handle){std::abort();}
Result FSFILE_Close(Handle){std::abort();}
Result FSUSER_GetSdmcArchiveResource(FS_ArchiveResource*){std::abort();}
Result AM_StartCiaInstall(int,Handle*){std::abort();}
Result FSFILE_Write(Handle,u32*,u64,const void*,u32,int){std::abort();}
Result AM_FinishCiaInstall(Handle){std::abort();}
Result APT_PrepareToDoApplicationJump(int,u64,int){std::abort();}
Result APT_DoApplicationJump(void*,size_t,void*){std::abort();}
static void markVisible(){
    for(unsigned s=0;s<2;s++){
        std::fill(data(s,current[s]),data(s,current[s])+count(s),VisibleMark);
        before[s]=pixels[s][current[s]];
    }
}
static void guards(){
    for(unsigned s=0;s<2;s++)for(unsigned i=0;i<2;i++)
        assert(pixels[s][i].front()==Guard&&pixels[s][i].back()==Guard);
}
static void ppm(const std::string& path){
    FILE* f=std::fopen(path.c_str(),"wb");assert(f);
    std::fprintf(f,"P6\n400 492\n255\n");
    for(unsigned y=0;y<492;y++)for(unsigned x=0;x<400;x++){
        u16 value=0;
        if(y<240)value=data(GFX_TOP,current[GFX_TOP])[x*240+239-y];
        else if(y>=252&&x>=40&&x<360)value=data(GFX_BOTTOM,current[GFX_BOTTOM])[(x-40)*240+239-(y-252)];
        unsigned char rgb[3]={static_cast<unsigned char>(((value>>11)&31)*255/31),static_cast<unsigned char>(((value>>5)&63)*255/63),static_cast<unsigned char>((value&31)*255/31)};
        assert(std::fwrite(rgb,1,3,f)==3);
    }
    assert(std::fclose(f)==0);
}
int main(int argc,char** argv){
    assert(platform::init());
    for(unsigned frame=0;frame<4;frame++){
        for(unsigned s=0;s<2;s++){
            // Mark the visible front buffer so writing a stale console pointer
            // fails even when two consecutive frames have identical content.
            std::fill(data(s,current[s]),data(s,current[s])+count(s),VisibleMark);
            before[s]=pixels[s][current[s]];
        }
        platform::display("","",frame%2?platform::UserPrompt::approve:platform::UserPrompt::arm);
        assert(waits==frame+1&&swaps==frame+1&&flushes==frame+1);
        assert(data(GFX_TOP,current[GFX_TOP])[100*240+235]==0x2211);
        assert(data(GFX_TOP,current[GFX_TOP])[0]==0);
        assert(data(GFX_BOTTOM,current[GFX_BOTTOM])[0]==0);
        assert(data(GFX_BOTTOM,current[GFX_BOTTOM])[76*240+239-150]!=0);
        for(unsigned s=0;s<2;s++)for(unsigned i=0;i<2;i++){
            assert(pixels[s][i].front()==Guard&&pixels[s][i].back()==Guard);
        }
    }
    platform::Dashboard ui;ui.listening=true;ui.armed=true;ui.build=6;ui.phase="RECEIVING FILE";ui.target="MORROWIND GUIDEBOOK";
    ui.total=100;ui.done=25;ui.instruction="Keep this app and the lid open.";ui.next="Next: file check, then approval.";
    for(unsigned frame=0;frame<6;frame++){
        markVisible();ui.recovery=frame%2;ui.autonomous=frame==2;ui.prompt=frame==3?platform::UserPrompt::approve:frame==4?platform::UserPrompt::arm:frame==5?platform::UserPrompt::review:platform::UserPrompt::none;
        platform::dashboard(ui);guards();
        // The recovery LCD background matches its purple art; main stays blue.
        const u16 background=ui.recovery?u16(((23>>3)<<11)|((12>>2)<<5)|(32>>3)):u16(((15>>3)<<11)|((22>>2)<<5)|(34>>3));
        assert(data(GFX_TOP,current[GFX_TOP])[0]==background);
        assert(data(GFX_BOTTOM,current[GFX_BOTTOM])[0]==background);
        assert(waits==5+frame&&swaps==5+frame&&flushes==5+frame);
        assert(data(GFX_TOP,current[GFX_TOP])[224*240+239-10]==0x2211);
        assert(data(GFX_TOP,current[GFX_TOP])[30*240+239-182]!=data(GFX_TOP,current[GFX_TOP])[350*240+239-182]);
    }
    if(argc==6&&std::string(argv[1])=="--preview"){
        FILE* font=std::fopen(argv[4],"rb");assert(font);assert(std::fread(testFont,1,sizeof(testFont),font)==sizeof(testFont));std::fclose(font);
        FILE* art=std::fopen(argv[3],"rb");assert(art);assert(std::fread(screen_banner_bin,1,sizeof(screen_banner_bin),art)==sizeof(screen_banner_bin));std::fclose(art);
        ui.recovery=std::string(argv[5])=="recovery";ui.autonomous=false;ui.active=true;ui.build=ui.recovery?6:7;ui.version=7;
        ui.target=ui.recovery?"REMOTEPILOT":"MORROWIND GUIDEBOOK";ui.address="PAIRED LOCAL NETWORK";
        ui.total=264*1048576ULL;ui.done=92*1048576ULL;ui.hash=std::string("0123456789abcdef0123456789abcdef")+"0123456789abcdef0123456789abcdef";
        ui.prompt=platform::UserPrompt::none;ui.instruction="No button press needed. Keep this app and the lid open.";
        markVisible();platform::dashboard(ui);guards();ppm(std::string(argv[2])+"-transfer.ppm");
        ui.phase="AWAITING APPROVAL";ui.done=ui.total;ui.prompt=platform::UserPrompt::approve;
        ui.instruction="Approve the title, version and hash below. B rejects this update.";ui.next="After A: recheck, install and confirm.";
        markVisible();platform::dashboard(ui);guards();ppm(std::string(argv[2])+"-approval.ppm");
        ui.phase="INSTALLING";ui.done=72*1048576ULL;ui.autonomous=true;ui.prompt=platform::UserPrompt::none;
        ui.instruction="Automatic install enabled for this job. No A press needed.";ui.next="Next: PC confirms installed version.";
        markVisible();platform::dashboard(ui);guards();ppm(std::string(argv[2])+"-autonomous.ppm");
        ui.phase="READY FOR TRANSFER";ui.total=0;ui.done=0;ui.target.clear();ui.hash.clear();ui.active=false;ui.autonomous=false;
        ui.instruction=ui.recovery?"On the PC, send the main companion update.":"On the PC, select a CIA app to send.";
        ui.next=ui.recovery?"Only RemotePilot companion CIAs here.":"CIA apps now. Y: optional auto mode.";
        markVisible();platform::dashboard(ui);guards();ppm(std::string(argv[2])+"-ready.ppm");
    }
    assert(!platform::launch());
    assert(!platform::prepareLaunch(0));
    assert(platform::prepareLaunch(launchTarget));
    assert(!chainloaderSet); // Preparing must not begin an APT transition.
    assert(platform::launch());
    assert(chainloaderSet);
    assert(!platform::running()); // Leave the main loop so cleanup runs first.
    platform::exit();
    puts("Display regression: visible buffers untouched while drawing; both back buffers rebound; RGB565 artwork bounds, vblank and deferred chainload PASS");
}

void osSetSpeedupEnable(bool enabled){assert(enabled);}

void aptSetChainloader(u64 id,u8 media){assert(id==launchTarget&&media==MEDIATYPE_SD);chainloaderSet=true;}
