// SPDX-License-Identifier: GPL-3.0-only
#include "platform.hpp"
#include <3ds.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <sstream>
#include <malloc.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include "screen_banner_bin.h"

namespace platform {
static void* socBuffer;
static Handle installHandle;
static bool amReady, psReady, socReady;
static PrintConsole top, bottom;
bool init() {
    gfxInit(GSP_RGB565_OES, GSP_RGB565_OES, false);
    consoleInit(GFX_TOP, &top); consoleInit(GFX_BOTTOM, &bottom);
    // consoleInit chooses single buffering and caches a framebuffer pointer.
    // Render complete frames into alternating back buffers instead of clearing
    // the LCD's visible buffer, which produced flicker and a moving tear line.
    gfxSetDoubleBuffering(GFX_TOP, true);
    gfxSetDoubleBuffering(GFX_BOTTOM, true);
    amReady = R_SUCCEEDED(amInit()); psReady = R_SUCCEEDED(psInit());
    socBuffer = memalign(0x1000, 1024 * 1024);
    socReady = socBuffer && R_SUCCEEDED(socInit(static_cast<u32*>(socBuffer), 1024 * 1024));
    return amReady && psReady && socReady;
}
void exit() {
    if (installHandle) AM_CancelCIAInstall(installHandle);
    if (socReady) socExit();
    std::free(socBuffer);
    if (psReady) psExit();
    if (amReady) amExit();
    gfxExit();
}
bool running() { gspWaitForVBlank(); return aptMainLoop(); }
uint64_t milliseconds() { return svcGetSystemTick() / (SYSCLOCK_ARM11 / 1000); }
std::string networkAddress() { in_addr ip{}; ip.s_addr=gethostid(); return inet_ntoa(ip); }
unsigned keys() {
    hidScanInput(); u32 k = hidKeysDown();
    // HID does not identify the source of a key. Disable Luma injection before
    // approving an installation; do not describe this as physical authentication.
    return ((k&KEY_A)?1:0)|((k&KEY_B)?2:0)|((k&KEY_X)?4:0)|((k&KEY_START)?8:0)|((k&KEY_Y)?16:0);
}
bool random(void* p, size_t n) { return psReady && R_SUCCEEDED(PS_GenerateRandomBytes(p, n)); }
bool titles(std::vector<Title>& out) {
    u32 count=0, read=0;
    if (!amReady || R_FAILED(AM_GetTitleCount(MEDIATYPE_SD, &count)) || count>4096) return false;
    std::vector<u64> ids(count);
    if (count && R_FAILED(AM_GetTitleList(&read, MEDIATYPE_SD, count, ids.data()))) return false;
    for (u32 i=0;i<read;i++) if ((ids[i]>>32)==0x00040000) {
        AM_TitleInfo info{};
        if (R_FAILED(AM_GetTitleInfo(MEDIATYPE_SD, 1, &ids[i], &info))) return false;
        out.push_back({info.titleID, info.version});
        if (out.size()>512) return false;
    }
    return true;
}
bool inspect(const std::string& path, Title& title, uint64_t& required) {
    Handle file=0; AM_TitleInfo info{};
    std::string relative=path.substr(5); // sdmc:/... -> /...
    Result result=FSUSER_OpenFileDirectly(&file, ARCHIVE_SDMC, fsMakePath(PATH_EMPTY, ""),
        fsMakePath(PATH_ASCII, relative.c_str()), FS_OPEN_READ, 0);
    if (R_FAILED(result)) return false;
    result=AM_GetCiaFileInfo(MEDIATYPE_SD, &info, file);
    if (R_SUCCEEDED(result)) result=AM_GetCiaRequiredSpace(&required, MEDIATYPE_SD, file);
    FSFILE_Close(file);
    title={info.titleID, info.version};
    return R_SUCCEEDED(result);
}
uint64_t freeSpace() {
    FS_ArchiveResource r{};
    if (R_FAILED(FSUSER_GetSdmcArchiveResource(&r))) return 0;
    return uint64_t(r.freeClusters)*r.clusterSize;
}
bool startInstall() { return !installHandle && R_SUCCEEDED(AM_StartCiaInstall(MEDIATYPE_SD, &installHandle)); }
bool writeInstall(uint64_t offset, const void* data, size_t n) {
    u32 written=0;
    return installHandle && R_SUCCEEDED(FSFILE_Write(installHandle, &written, offset, data, n, 0)) && written==n;
}
bool finishInstall() {
    Handle h=installHandle; installHandle=0;
    // Finish consumes the AM handle; failed finish is an unknown outcome.
    return h && R_SUCCEEDED(AM_FinishCiaInstall(h));
}
bool cancelInstall() {
    Handle h=installHandle; installHandle=0;
    return !h || R_SUCCEEDED(AM_CancelCIAInstall(h));
}
bool prepareLaunch(uint64_t id) { return R_SUCCEEDED(APT_PrepareToDoApplicationJump(0, id, MEDIATYPE_SD)); }
bool launch() {
    static u8 params[0x300]{}, hmac[0x20]{};
    return R_SUCCEEDED(APT_DoApplicationJump(params, sizeof(params), hmac));
}
static void largeText(const char* text,unsigned left,unsigned y,u16 color) {
    const auto& font=bottom.font;
    for(unsigned n=0;text[n];n++) {
        int ch=static_cast<unsigned char>(text[n])-font.asciiOffset;
        if(ch<0||ch>=font.numChars)continue;
        const u8* glyph=font.gfx+ch*8;
        for(unsigned row=0;row<8;row++)for(unsigned col=0;col<8;col++)
            for(unsigned dy=0;dy<3;dy++)for(unsigned dx=0;dx<3;dx++) {
                unsigned px=left+n*24+col*3+dx, py=y+row*3+dy;
                if(px<320&&py<240)bottom.frameBuffer[px*240+239-py]=(glyph[row]&(0x80>>col))?color:0;
            }
    }
}
void display(const std::string& a, const std::string& b, UserPrompt prompt) {
    // Refresh BOTH cached pointers after each swap. consoleClear and printf
    // flush during rendering; with these pointers they touch only back buffers.
    top.frameBuffer=reinterpret_cast<u16*>(gfxGetFramebuffer(GFX_TOP,GFX_LEFT,nullptr,nullptr));
    bottom.frameBuffer=reinterpret_cast<u16*>(gfxGetFramebuffer(GFX_BOTTOM,GFX_LEFT,nullptr,nullptr));
    std::memset(top.frameBuffer,0,400*240*sizeof(u16));
    std::memset(bottom.frameBuffer,0,320*240*sizeof(u16));
    consoleSelect(&top); printf("\x1b[15;1H\x1b[36m%s\x1b[0m", a.c_str());
    // Console uses a rotated RGB565 framebuffer. Art occupies a reserved header;
    // status and controls below stay readable and never draw over the artwork.
    if(top.frameBuffer && screen_banner_bin_size==200*100*2) {
        for(unsigned y=0;y<100;y++)for(unsigned x=0;x<200;x++) {
            unsigned at=(y*200+x)*2;
            top.frameBuffer[(100+x)*240+(239-(4+y))] = screen_banner_bin[at] | (screen_banner_bin[at+1]<<8);
        }
    }
    consoleSelect(&bottom); printf("\x1b[1;1H\x1b[36m%s\x1b[0m", b.c_str());
    if(prompt!=UserPrompt::none) {
        // Gentle attention pulse; the large instruction stays legible until the
        // job/arming state changes, never disappearing on a timer or key-down.
        u16 color=(milliseconds()/700)%2?0xffff:0x4ff9;
        for(unsigned x=8;x<312;x++)for(unsigned dy=0;dy<3;dy++) {
            bottom.frameBuffer[x*240+239-(137+dy)]=color;
            bottom.frameBuffer[x*240+239-(221+dy)]=color;
        }
        largeText(prompt==UserPrompt::approve?"PRESS A":prompt==UserPrompt::review?"PRESS B":"PRESS X",76,150,color);
        largeText("ON THIS 3DS",28,184,color);
    }
    gfxFlushBuffers(); gfxSwapBuffers();
    gspWaitForVBlank(); // finish presentation before a later frame reuses its old buffer.
}
static u16 rgb(unsigned r,unsigned g,unsigned b){return ((r>>3)<<11)|((g>>2)<<5)|(b>>3);}
static void rect(PrintConsole& screen,int width,int x,int y,int w,int h,u16 color) {
    int left=std::max(0,x),right=std::min(width,x+w),up=std::max(0,y),down=std::min(240,y+h);
    for(int px=left;px<right;px++)std::fill(screen.frameBuffer+px*240+240-down,screen.frameBuffer+px*240+240-up,color);
}
static void card(PrintConsole& screen,int width,int x,int y,int w,int h,u16 line,u16 fill) {
    rect(screen,width,x+5,y,w-10,h,line);rect(screen,width,x,y+5,w,h-10,line);
    rect(screen,width,x+2,y+2,w-4,h-4,line);
    rect(screen,width,x+6,y+1,w-12,h-2,fill);rect(screen,width,x+1,y+6,w-2,h-12,fill);
    rect(screen,width,x+3,y+3,w-6,h-6,fill);
}
static void text(PrintConsole& screen,int width,int left,int y,const std::string& value,int scale,u16 color) {
    const auto& font=screen.font;int x=left;
    for(unsigned char c:value) {
        if(c=='\n'){x=left;y+=10*scale;continue;}
        int ch=int(c)-font.asciiOffset;
        if(ch>=0&&ch<font.numChars) {
            const u8* glyph=font.gfx+ch*8;
            for(int row=0;row<8;row++)for(int col=0;col<8;col++)if(glyph[row]&(0x80>>col))
                rect(screen,width,x+col*scale,y+row*scale,scale,scale,color);
        }
        x+=8*scale;
    }
}
static void paragraph(int y,const std::string& value,u16 color,unsigned maxLines=3) {
    std::istringstream words(value);std::string word,line;unsigned lines=0;
    while(words>>word) {
        if(line.size()+word.size()+1>34&&!line.empty()) {
            text(bottom,320,24,y,line,1,color);line.clear();y+=12;if(++lines>=maxLines)return;
        }
        if(!line.empty())line+=' ';
        line+=word;
    }
    if(!line.empty()&&lines<maxLines)text(bottom,320,24,y,line.substr(0,34),1,color);
}
void dashboard(const Dashboard& ui) {
    // Both screens are composed entirely offscreen and presented together.
    top.frameBuffer=reinterpret_cast<u16*>(gfxGetFramebuffer(GFX_TOP,GFX_LEFT,nullptr,nullptr));
    bottom.frameBuffer=reinterpret_cast<u16*>(gfxGetFramebuffer(GFX_BOTTOM,GFX_LEFT,nullptr,nullptr));
    // Recovery's gold shield sits in a purple nebula. Carry that palette across
    // both LCDs instead of placing its art on the main app's blue/teal chrome.
    const u16 bg=ui.recovery?rgb(23,12,32):rgb(15,22,34);
    const u16 panel=ui.recovery?rgb(43,24,53):rgb(25,36,51);
    const u16 line=ui.recovery?rgb(112,66,119):rgb(57,76,94);
    const u16 ink=ui.recovery?rgb(255,242,221):rgb(235,242,250);
    const u16 muted=ui.recovery?rgb(198,170,207):rgb(160,181,198);
    const u16 accent=ui.recovery?rgb(255,189,81):rgb(120,201,180),amber=rgb(247,201,139);
    rect(top,400,0,0,400,240,bg);rect(bottom,320,0,0,320,240,bg);
    text(top,400,16,12,ui.recovery?"RP Recovery":"RemotePilot",2,ink);
    text(top,400,16,35,ui.recovery?"COMPANION REPAIR":"GAME & TOOL UPDATES",1,accent);
    text(top,400,16,60,ui.listening?"PAIRED LISTENER READY":"NOT LISTENING",1,ui.listening?accent:amber);
    text(top,400,16,76,ui.address,1,muted);
    text(top,400,16,94,std::string(ui.armed?"ARMED":"SESSION OFF")+"  BUILD "+std::to_string(ui.build),1,ui.armed?accent:amber);
    if(screen_banner_bin_size==200*100*2)for(unsigned y=0;y<80;y++)for(unsigned x=0;x<160;x++) {
        unsigned at=((y*100/80)*200+x*200/160)*2;
        top.frameBuffer[(224+x)*240+239-(10+y)]=screen_banner_bin[at]|(screen_banner_bin[at+1]<<8);
    }
    card(top,400,12,112,376,82,line,panel);
    text(top,400,24,121,ui.target.empty()?"NO UPDATE PENDING":ui.target.substr(0,44),1,accent);
    text(top,400,24,139,ui.phase.substr(0,22),2,ink);
    if(ui.total) {
        char counts[64];std::snprintf(counts,sizeof(counts),"%.1f / %.1f MiB",double(ui.done)/1048576,double(ui.total)/1048576);
        text(top,400,24,163,counts,1,muted);
        unsigned percent=unsigned(std::min<uint64_t>(100,ui.done*100/ui.total));
        text(top,400,336,163,std::to_string(percent)+"%",1,ink);
        rect(top,400,24,180,352,6,bg);rect(top,400,24,180,int(352*std::min(ui.done,ui.total)/ui.total),6,accent);
    } else text(top,400,24,167,"Ready for the paired PC",1,muted);
    text(top,400,16,204,ui.autonomous?"AUTO INSTALL ON  |  Y: OFF":ui.active?"MANUAL APPROVAL FOR THIS JOB":"MANUAL APPROVAL  |  Y: AUTO",1,ui.autonomous?amber:muted);
    text(top,400,16,223,"X: ARM/OFF  B: CANCEL  START: EXIT",1,muted);
    text(bottom,320,16,14,"YOUR NEXT ACTION ON THIS 3DS",1,accent);
    const bool attention=ui.prompt!=UserPrompt::none;
    const u16 pulse=attention&&(milliseconds()/700)%2?ink:amber;
    card(bottom,320,12,33,296,100,attention?pulse:line,panel);
    std::string action=ui.prompt==UserPrompt::approve?"PRESS A":ui.prompt==UserPrompt::arm?"PRESS X":ui.prompt==UserPrompt::review?"PRESS B":"KEEP APP OPEN";
    int scale=attention?3:2;
    text(bottom,320,(320-int(action.size())*8*scale)/2,46,action,scale,attention?pulse:ink);
    paragraph(83,ui.instruction,ink);
    text(bottom,320,16,146,ui.target.empty()?"PAIRING STAYS PRIVATE":(ui.target+" v"+std::to_string(ui.version)).substr(0,36),1,accent);
    if(ui.hash.size()==64) {
        text(bottom,320,16,164,"FILE SHA-256",1,muted);
        text(bottom,320,24,177,ui.hash.substr(0,32),1,muted);
        text(bottom,320,24,189,ui.hash.substr(32),1,muted);
    }
    paragraph(213,ui.next,muted,2);
    gfxFlushBuffers();gfxSwapBuffers();gspWaitForVBlank();
}
}
