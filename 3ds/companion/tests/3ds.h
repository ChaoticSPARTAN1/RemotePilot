// Desktop-only libctru graphics double for the real platform.cpp regression test.
#pragma once
#include <cstdint>
using u8=uint8_t; using u16=uint16_t; using u32=uint32_t; using u64=uint64_t;
using Handle=uint32_t; using Result=int;
enum gfxScreen_t {GFX_TOP, GFX_BOTTOM};
enum gfx3dSide_t {GFX_LEFT};
enum GSPGPU_FramebufferFormat {GSP_BGR8_OES, GSP_RGB565_OES};
struct ConsoleFont {u8* gfx;int asciiOffset;int numChars;};
struct PrintConsole {u16* frameBuffer;ConsoleFont font;};
struct AM_TitleInfo {u64 titleID; u16 version;};
struct FS_ArchiveResource {u64 freeClusters, clusterSize;};
struct FS_Path {int type;};
constexpr int KEY_A=1,KEY_B=2,KEY_X=4,KEY_START=8,KEY_Y=16;
constexpr int MEDIATYPE_SD=1,ARCHIVE_SDMC=1,PATH_EMPTY=0,PATH_ASCII=1,FS_OPEN_READ=1;
constexpr uint64_t SYSCLOCK_ARM11=268123480;
#define R_SUCCEEDED(x) ((x)>=0)
#define R_FAILED(x) ((x)<0)
void gfxInit(GSPGPU_FramebufferFormat,GSPGPU_FramebufferFormat,bool);
PrintConsole* consoleInit(gfxScreen_t,PrintConsole*);
PrintConsole* consoleSelect(PrintConsole*);
void gfxSetDoubleBuffering(gfxScreen_t,bool);
u8* gfxGetFramebuffer(gfxScreen_t,gfx3dSide_t,u16*,u16*);
void gfxFlushBuffers(); void gfxSwapBuffers(); void gfxExit();
void gspWaitForVBlank(); bool aptMainLoop(); uint64_t svcGetSystemTick();
void hidScanInput(); u32 hidKeysDown();
Result amInit(); void amExit(); Result psInit(); void psExit();
Result socInit(u32*,u32); void socExit();
Result PS_GenerateRandomBytes(void*,size_t);
Result AM_GetTitleCount(int,u32*); Result AM_GetTitleList(u32*,int,u32,u64*);
Result AM_GetTitleInfo(int,u32,u64*,AM_TitleInfo*);
FS_Path fsMakePath(int,const char*);
Result FSUSER_OpenFileDirectly(Handle*,int,FS_Path,FS_Path,int,int);
Result AM_GetCiaFileInfo(int,AM_TitleInfo*,Handle); Result AM_GetCiaRequiredSpace(u64*,int,Handle);
Result FSFILE_Close(Handle); Result FSUSER_GetSdmcArchiveResource(FS_ArchiveResource*);
Result AM_StartCiaInstall(int,Handle*); Result FSFILE_Write(Handle,u32*,u64,const void*,u32,int);
Result AM_FinishCiaInstall(Handle); Result AM_CancelCIAInstall(Handle);
Result APT_PrepareToDoApplicationJump(int,u64,int); Result APT_DoApplicationJump(void*,size_t,void*);
