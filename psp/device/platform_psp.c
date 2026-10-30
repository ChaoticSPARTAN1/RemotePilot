/* platform_psp.c - RemotePilot PSP companion: the PSP's own platform layer for
rp2_device.c and rp2_actions.c, as an EBOOT started from the XMB.

Its screens (ui/screens.c) guide three things from a home screen:
  TRIANGLE  Back up: the PSP's system settings, flash1:/, into a new folder
            under ms0:/BACKUP (rp2_backup.c), with or without Wi-Fi;
  SQUARE    Restore: a backup put back on flash1 (rp2_restore.c), only after
            it is checked and ✕ is held for two seconds, by the kernel helper
            rp_flash.prx beside the EBOOT, then a restart;
  CROSS     Connect: joins the Wi-Fi network saved as connection 1 (only
            from this screen, and only with the WLAN switch on), shows its
            address, and answers the viewer on the config's port: pairing and
            every request as rp2_device.c has them, peers on private IPv4
            networks only.
At start it compares the settings with the newest backup and says so.

The pairing file is ms0:/remotepilot/remotepilot.cfg (before 2026-10-30, and
still read: ms0:/halo/remotepilot.cfg), written by the
viewer's Prepare pairing. Without it nothing listens. Files are read-only to
the viewer; the backup is the only write it can ask for, and restore can't be
asked for over the network at all.

Run on a PSP-1000 (6.61, ARK-4): a user-mode EBOOT reads flash1, and the
backup works. Still to see on hardware: the drawn screens, the kernel
helper's writes, the socket timeout's unit (microseconds here) and how long
connection 1 takes to come up. */
#include <pspkernel.h>
#include <pspctrl.h>
#include <pspdisplay.h>
#include <psppower.h>
#include <psprtc.h>
#include <psputility.h>
#include <pspnet.h>
#include <pspnet_inet.h>
#include <pspnet_apctl.h>
#include <pspwlan.h>
#include <psputility_netparam.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rp2_device.h"
#include "rp2_actions.h"
#include "ui/screens.h"

PSP_MODULE_INFO("RemotePilot", PSP_MODULE_USER, 1, 0);
PSP_MAIN_THREAD_ATTR(PSP_THREAD_ATTR_USER);
PSP_HEAP_SIZE_KB(4096);

#define CONFIG_PATH "ms0:/remotepilot/remotepilot.cfg"
#define CONFIG_PATH_OLD "ms0:/halo/remotepilot.cfg"
#define LOG_PATH "ms0:/halo/log/log.txt"
/* a request must arrive within 3 s; a reply may wait up to 10 s for room to
send (a PSP-1000 on a busy 802.11b network can stall that long mid-image) */
#define SOCKET_TIMEOUT_US 3000000u
#define SEND_TIMEOUT_US 10000000u
#define CONNECT_TIMEOUT_MS 30000u
#define WIFI_REPORT "ms0:/halo/remotepilot-wifi.txt"

void p2p_hmac_sha256(const unsigned char *key, int key_size, const void *data, int size, unsigned char *digest);

static volatile int running = 1;
static struct rp2_config config;
static struct rp2_device device;
static struct rp2_platform platform;
static unsigned char space[RP2_REPLY_HEADROOM + 4 * 1024 * 1024] __attribute__((aligned(64)));

/* what the status page shows; written by the server thread, read by main */
static volatile int net_state;  /* 0 not started, 1 joining, 2 up, -1 failed, -2 no pairing */
static char address_text[32] = "-";
static volatile unsigned int served, refused;
static char last_kind[RP2_MAX_KIND + 1] = "-";
static volatile unsigned int remote_buttons, remote_frames;
static volatile int remote_lx = 128, remote_ly = 128;
static volatile double loop_fps;
static unsigned long long nonce_counter;
/* space is shared by the server thread's replies and the main thread's
backup, check and restore: one holds it at a time */
static SceUID space_lock = -1;
static struct rp2_backup_result backup_result;

/* a restore is writing flash1: quitting waits for it, never cuts it off */
static volatile int restoring;

/* HOME > Quit: main tidies up and exits; if it hasn't in 3 s (anything
stuck), the exit happens here anyway, so the PSP is never left at "Please
wait..." */
static int exit_callback(int arg1, int arg2, void *common)
{
	int waited;

	(void)arg1; (void)arg2; (void)common;
	running = 0;
	for (waited = 0; waited < 3000 || restoring; waited += 50)
		sceKernelDelayThread(50 * 1000);
	sceKernelExitGame();
	return 0;
}

static int callback_thread(SceSize args, void *argp)
{
	int callback;

	(void)args; (void)argp;
	callback = sceKernelCreateCallback("exit", exit_callback, NULL);
	sceKernelRegisterExitCallback(callback);
	sceKernelSleepThreadCB();
	return 0;
}

/* ----- rp2_platform */

/* when the request must have arrived by: a peer trickling a byte at a time
gets 10 s in all, not 3 s per byte */
static unsigned long long recv_deadline_us;

static int psp_recv(void *context, int socket, void *buffer, size_t size)
{
	(void)context;
	if ((unsigned long long)sceKernelGetSystemTimeWide() > recv_deadline_us)
		return -1;
	/* the firmware's own socket calls throughout: the ids rp2_serve is given
	are the firmware's, with no newlib descriptor table between */
	return (int)sceNetInetRecv(socket, buffer, size, 0);
}

static int psp_send(void *context, int socket, const void *buffer, size_t size)
{
	(void)context;
	return (int)sceNetInetSend(socket, buffer, size > 32768 ? 32768 : size, 0);
}

/* the nonce: unique per connection (a counter, the boot clock and the real
time clock) and unpredictable without the token (an HMAC under it). A user
mode EBOOT has no hardware random source of its own */
static int psp_random(void *context, unsigned char *out, size_t size)
{
	unsigned char block[32], seed[40];
	u64 tick = 0;
	size_t done = 0;

	(void)context;
	memset(seed, 0, sizeof(seed));
	while (done < size)
	{
		unsigned long long now = (unsigned long long)sceKernelGetSystemTimeWide();
		size_t take = size - done < sizeof(block) ? size - done : sizeof(block);

		sceRtcGetCurrentTick(&tick);
		nonce_counter++;
		memcpy(seed, "rp2nonce", 8);
		memcpy(seed + 8, &nonce_counter, 8);
		memcpy(seed + 16, &now, 8);
		memcpy(seed + 24, &tick, 8);
		memcpy(seed + 32, &done, sizeof(done) < 8 ? sizeof(done) : 8);
		p2p_hmac_sha256(config.token, RP2_TOKEN_BYTES, seed, (int)sizeof(seed), block);
		memcpy(out + done, block, take);
		done += take;
	}
	return 0;
}

static void psp_hmac(const unsigned char *key, size_t key_size, const unsigned char *data, size_t size,
                     unsigned char digest[32])
{
	p2p_hmac_sha256(key, (int)key_size, data, (int)size, digest);
}

/* rp2_platform.hold: the reply's memory, shared with the main thread's
backup, check and restore */
static void psp_hold(void *context, int on)
{
	(void)context;
	if (on)
		sceKernelWaitSema(space_lock, 1, NULL);
	else
		sceKernelSignalSema(space_lock, 1);
}

/* ----- rp2_device */

static int psp_frame(void *context, const void **pixels, int *stride, int *format)
{
	void *top = NULL;
	int width = 0, pixel_format = 0;

	(void)context;
	if (sceDisplayGetFrameBuf(&top, &width, &pixel_format, PSP_DISPLAY_SETBUF_NEXTFRAME) < 0 || !top || width < RP2_SCREEN_WIDTH)
		return -1;
	/* read through the uncached mirror: the GE and the CPU write VRAM */
	*pixels = (const void *)((unsigned int)top | 0x40000000u);
	*stride = width;
	*format = pixel_format;
	return 0;
}

static int psp_list(void *context, const char *path, struct rp2_entry *entries, int max)
{
	SceIoDirent entry;
	SceUID dir;
	int count = 0;

	(void)context;
	dir = sceIoDopen(path);
	if (dir < 0)
		return -1;
	for (;;)
	{
		memset(&entry, 0, sizeof(entry));
		if (sceIoDread(dir, &entry) <= 0 || count >= max)
			break;
		if (!strcmp(entry.d_name, ".") || !strcmp(entry.d_name, "..") || strlen(entry.d_name) >= sizeof(entries[0].name))
			continue;
		strcpy(entries[count].name, entry.d_name);
		entries[count].directory = FIO_S_ISDIR(entry.d_stat.st_mode) != 0;
		entries[count].size = (unsigned long)entry.d_stat.st_size;
		count++;
	}
	sceIoDclose(dir);
	return count;
}

static long psp_read(void *context, const char *path, unsigned long offset, void *buffer, unsigned long size,
                     unsigned long *total)
{
	SceUID file;
	SceOff length;
	int got;

	(void)context;
	file = sceIoOpen(path, PSP_O_RDONLY, 0);
	if (file < 0)
		return -1;
	length = sceIoLseek(file, 0, PSP_SEEK_END);
	if (length < 0 || sceIoLseek(file, (SceOff)offset, PSP_SEEK_SET) < 0)
	{
		sceIoClose(file);
		return -1;
	}
	*total = (unsigned long)length;
	got = sceIoRead(file, buffer, (SceSize)size);
	sceIoClose(file);
	return got < 0 ? -1 : got;
}

/* remote input drives the companion's own screens, held for its frames
(main reads it with the PSP's buttons); the nub moves as the D-pad */
static void psp_input(void *context, unsigned int buttons, int lx, int ly, int frames)
{
	(void)context;
	remote_buttons = buttons;
	remote_lx = lx;
	remote_ly = ly;
	remote_frames = (unsigned int)frames;
}

/* the remote buttons for this frame, one frame of their hold used up */
static unsigned int remote_held(void)
{
	unsigned int buttons;

	if (!remote_frames)
		return 0;
	remote_frames--;
	buttons = remote_buttons & (PSP_CTRL_UP | PSP_CTRL_DOWN | PSP_CTRL_LEFT | PSP_CTRL_RIGHT | PSP_CTRL_CROSS |
		PSP_CTRL_CIRCLE | PSP_CTRL_SQUARE | PSP_CTRL_TRIANGLE | PSP_CTRL_LTRIGGER | PSP_CTRL_RTRIGGER |
		PSP_CTRL_START | PSP_CTRL_SELECT);
	if (remote_ly < 64)
		buttons |= PSP_CTRL_UP;
	else if (remote_ly > 192)
		buttons |= PSP_CTRL_DOWN;
	if (remote_lx < 64)
		buttons |= PSP_CTRL_LEFT;
	else if (remote_lx > 192)
		buttons |= PSP_CTRL_RIGHT;
	return buttons;
}

static int psp_perf(void *context, double *fps, double *frame_ms, double *work_ms)
{
	(void)context;
	if (loop_fps <= 0)
		return -1;
	*fps = loop_fps;
	*frame_ms = 1000.0 / loop_fps;
	*work_ms = 0;
	return 0;
}

/* firmware, battery, memory and stick space; no MAC address or serial */
static size_t psp_report(void *context, char *out, size_t size)
{
	struct { unsigned long max_clusters, free_clusters, max_sectors, sector_size, sector_count; } info, *pointer = &info;
	unsigned long long free_bytes = 0;
	int firmware = sceKernelDevkitVersion(), length;

	(void)context;
	memset(&info, 0, sizeof(info));
	if (sceIoDevctl("ms0:", 0x02425818, &pointer, sizeof(pointer), NULL, 0) >= 0)
		free_bytes = (unsigned long long)info.free_clusters * info.sector_count * info.sector_size;
	length = snprintf(out, size,
		"RemotePilot PSP companion 1.0\nfirmware: %d.%d%d\nbattery: %d%%%s\nfree user memory: %u KB\n"
		"memory stick free: %llu MB\nserved: %u, refused: %u\n",
		(firmware >> 24) & 0xff, (firmware >> 16) & 0xff, (firmware >> 8) & 0xff, scePowerGetBatteryLifePercent(),
		scePowerIsPowerOnline() ? " (charging)" : "", (unsigned)(sceKernelTotalFreeMemSize() / 1024),
		free_bytes / (1024 * 1024), served, refused);
	return length > 0 && (size_t)length < size ? (size_t)length : 0;
}

static unsigned long long psp_now_ms(void *context)
{
	(void)context;
	return (unsigned long long)sceKernelGetSystemTimeWide() / 1000;
}

/* ----- the settings backup's writes: ms0:/BACKUP only (rp2_backup.c) */

static int psp_make_folder(void *context, const char *path)
{
	SceUID dir;

	(void)context;
	if (sceIoMkdir(path, 0777) >= 0)
		return 0;
	/* already there */
	dir = sceIoDopen(path);
	if (dir < 0)
		return -1;
	sceIoDclose(dir);
	return 0;
}

static int psp_write_new(void *context, const char *path, const void *data, unsigned long size)
{
	SceUID file;
	unsigned long done = 0;
	int ok;

	(void)context;
	/* O_EXCL: never over a file that is there */
	file = sceIoOpen(path, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_EXCL, 0777);
	if (file < 0)
		return -1;
	while (done < size)
	{
		int wrote = sceIoWrite(file, (const char *)data + done, (SceSize)(size - done));

		if (wrote <= 0)
			break;
		done += (unsigned long)wrote;
	}
	ok = done == size;
	return sceIoClose(file) >= 0 && ok ? 0 : -1;
}

static int psp_stamp(void *context, char *out, size_t size)
{
	ScePspDateTime now;
	int length;

	(void)context;
	if (sceRtcGetCurrentClockLocalTime(&now) < 0)
		return -1;
	length = snprintf(out, size, "%04u%02u%02u-%02u%02u%02u", now.year, now.month, now.day, now.hour, now.minute,
		now.second);
	return length > 0 && (size_t)length < size ? 0 : -1;
}

/* ----- the network: connection 1, then one connection at a time */

/* the saved network to join: the first one in Settings > Network Settings.
Its number isn't always 1: a network keeps its number when the ones before
it are deleted (a PSP-1000 had only #2 or later: "connection 1" wasn't
there). Found by wifi_gather; 0 when none is saved */
static int net_index;

/* the join's steps as the firmware reports them (the Wi-Fi check shows
them); written by its handler, read by the main thread */
static struct
{
	volatile int count, error, strength, channel;
	struct { int state, event, error; unsigned int ms; } step[WIFI_STEPS];
	unsigned long long from_us;
	char ip[16];
} join;

static void apctl_handler(int old_state, int new_state, int event, int error, void *arg)
{
	(void)old_state; (void)arg;
	if (error)
		join.error = error;
	if (join.count < WIFI_STEPS)
	{
		join.step[join.count].state = new_state;
		join.step[join.count].event = event;
		join.step[join.count].error = error;
		join.step[join.count].ms = (unsigned int)((sceKernelGetSystemTimeWide() - join.from_us) / 1000);
		join.count++;
	}
}

static int net_up(void)
{
	union SceNetApctlInfo info;
	unsigned int waited;
	int state = 0, last = -1;

	if (sceUtilityLoadNetModule(PSP_NET_MODULE_COMMON) < 0 || sceUtilityLoadNetModule(PSP_NET_MODULE_INET) < 0)
		return -1;
	if (sceNetInit(128 * 1024, 42, 4 * 1024, 42, 4 * 1024) < 0 || sceNetInetInit() < 0 || sceNetApctlInit(0x8000, 48) < 0)
		return -1;
	memset(&join, 0, sizeof(join));
	join.from_us = sceKernelGetSystemTimeWide();
	sceNetApctlAddHandler(apctl_handler, NULL);
	net_state = 1;
	if (net_index <= 0 || sceNetApctlConnect(net_index) < 0)
		return -1;
	for (waited = 0; running && waited < CONNECT_TIMEOUT_MS; waited += 50)
	{
		if (sceNetApctlGetState(&state) < 0)
			return -1;
		if (state == PSP_NET_APCTL_STATE_GOT_IP)
			break;
		/* back to disconnected after joining began: the network refused */
		if (state == PSP_NET_APCTL_STATE_DISCONNECTED && last > PSP_NET_APCTL_STATE_DISCONNECTED)
			return -1;
		last = state;
		sceKernelDelayThread(50 * 1000);
	}
	if (state != PSP_NET_APCTL_STATE_GOT_IP || sceNetApctlGetInfo(PSP_NET_APCTL_INFO_IP, &info) < 0)
		return -1;
	snprintf(address_text, sizeof(address_text), "%s", info.ip);
	snprintf(join.ip, sizeof(join.ip), "%s", info.ip);
	if (sceNetApctlGetInfo(PSP_NET_APCTL_INFO_STRENGTH, &info) >= 0)
		join.strength = info.strength;
	if (sceNetApctlGetInfo(PSP_NET_APCTL_INFO_CHANNEL, &info) >= 0)
		join.channel = info.channel;
	return 0;
}

static void net_down(void)
{
	sceNetApctlDisconnect();
	sceNetApctlTerm();
	sceNetInetTerm();
	sceNetTerm();
	sceUtilityUnloadNetModule(PSP_NET_MODULE_INET);
	sceUtilityUnloadNetModule(PSP_NET_MODULE_COMMON);
}

/* the PSP's own non-blocking option (BSD's is fcntl, which its inet lacks) */
#define PSP_SO_NONBLOCK 0x1009

static SceUID server_id = -1;

static int server_thread(SceSize args, void *argp)
{
	struct sockaddr_in address;
	struct rp2_reply reply;
	int listener, one = 1, off = 0;

	(void)args; (void)argp;
	if (net_up() < 0)
	{
		net_state = -1;
		return 0;
	}
	listener = sceNetInetSocket(AF_INET, SOCK_STREAM, 0);
	memset(&address, 0, sizeof(address));
	address.sin_family = AF_INET;
	address.sin_port = htons((unsigned short)config.port);
	address.sin_addr.s_addr = htonl(INADDR_ANY);
	sceNetInetSetsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
	/* accept never blocks: the loop sees running go to 0 within 0.1 s, so
	quitting doesn't wait on a connection that never comes (it did: HOME >
	Quit sat at "Please wait..." for good) */
	sceNetInetSetsockopt(listener, SOL_SOCKET, PSP_SO_NONBLOCK, &one, sizeof(one));
	if (listener < 0 || sceNetInetBind(listener, (struct sockaddr *)&address, sizeof(address)) < 0 ||
	    sceNetInetListen(listener, 2) < 0)
	{
		net_state = -1;
		return 0;
	}
	net_state = 2;
	reply.data = space + RP2_REPLY_HEADROOM;
	reply.capacity = sizeof(space) - RP2_REPLY_HEADROOM;
	while (running)
	{
		struct sockaddr_in peer;
		socklen_t peer_size = sizeof(peer);
		unsigned int timeout = SOCKET_TIMEOUT_US, send_timeout = SEND_TIMEOUT_US;
		int send_buffer = 65536;
		int client;

		/* a short address leaves 0.0.0.0, which isn't answered */
		memset(&peer, 0, sizeof(peer));
		client = sceNetInetAccept(listener, (struct sockaddr *)&peer, &peer_size);
		if (client < 0)
		{
			sceKernelDelayThread(100 * 1000);
			continue;
		}
		if (!rp2_private_ipv4(ntohl(peer.sin_addr.s_addr)))
		{
			refused++;
			sceNetInetClose(client);
			continue;
		}
		/* the connection itself blocks, with its timeouts */
		sceNetInetSetsockopt(client, SOL_SOCKET, PSP_SO_NONBLOCK, &off, sizeof(off));
		sceNetInetSetsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
		sceNetInetSetsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &send_timeout, sizeof(send_timeout));
		sceNetInetSetsockopt(client, SOL_SOCKET, SO_SNDBUF, &send_buffer, sizeof(send_buffer));
		/* space is taken only once the request's MAC checks (psp_hold) */
		recv_deadline_us = (unsigned long long)sceKernelGetSystemTimeWide() + 10000000ull;
		if (rp2_serve(&platform, &config, client, &reply) == 0)
		{
			served++;
			snprintf(last_kind, sizeof(last_kind), "%s", reply.kind);
		}
		else
			refused++;
		sceNetInetClose(client);
	}
	sceNetInetClose(listener);
	return 0;
}

/* ----- the pairing file */

static int config_load(void)
{
	char text[1024];
	SceUID file = sceIoOpen(CONFIG_PATH, PSP_O_RDONLY, 0);

	if (file < 0)
		file = sceIoOpen(CONFIG_PATH_OLD, PSP_O_RDONLY, 0);
	int size;

	if (file < 0)
		return -1;
	size = sceIoRead(file, text, sizeof(text) - 1);
	sceIoClose(file);
	if (size <= 0 || rp2_config_parse(text, (size_t)size, &config) || !config.session_on)
		return -1;
	memset(text, 0, sizeof(text));
	return 0;
}

/* ----- the screen: drawn in RAM, copied to one of two VRAM buffers, shown
at the next vertical blank (ui/screens.c draws it) */

#define VRAM_STRIDE 512
#define VRAM_BUFFER (VRAM_STRIDE * UI_H * 4)

static uint32_t *drawn, *backdrop;
static int shown_buffer;
static SceUID main_thread;
static struct view view;
static struct rp2_restore_plan plan;
static struct rp2_flash_job job;
static unsigned long long started_us;
static char helper_path[160];
static int net_started;

static void present(void)
{
	struct ui ui = { drawn, VRAM_STRIDE };
	uint32_t *target;
	int y;

	view.frame = (unsigned int)((sceKernelGetSystemTimeWide() - started_us) * 60 / 1000000);
	screens_draw(&ui, backdrop, &view);
	shown_buffer ^= 1;
	/* the uncached mirror: what is copied is what the display reads */
	target = (uint32_t *)(0x44000000u + (unsigned int)shown_buffer * VRAM_BUFFER);
	for (y = 0; y < UI_H; y++)
		memcpy(target + y * VRAM_STRIDE, drawn + y * VRAM_STRIDE, UI_W * 4);
	sceDisplaySetFrameBuf((void *)(0x04000000u + (unsigned int)shown_buffer * VRAM_BUFFER), VRAM_STRIDE,
		PSP_DISPLAY_PIXEL_FORMAT_8888, PSP_DISPLAY_SETBUF_NEXTFRAME);
	sceDisplayWaitVblankStart();
}

/* rp2_device.progress: a backup or restore going; drawn only from the main
thread (the server thread's remote backup just counts) */
static void psp_progress(void *context, const char *what, int done)
{
	(void)context;
	view.backup.done = done;
	view.restore.done = done;
	snprintf(view.backup.what, sizeof(view.backup.what), "%s", what);
	if (sceKernelGetThreadId() == main_thread)
		present();
}

/* ----- the restore's writes: rp_flash.prx, the kernel helper beside the EBOOT */

static int psp_flash_restore(void *context, struct rp2_flash_job *flash_job)
{
	struct rp2_flash_job *pointer = flash_job;
	SceUID module;
	int status = 0, k;

	(void)context;
	module = sceKernelLoadModule(helper_path, 0, NULL);
	if (module < 0)
		return -1;
	if (sceKernelStartModule(module, sizeof(pointer), &pointer, &status, NULL) < 0)
	{
		sceKernelUnloadModule(module);
		return -1;
	}
	sceKernelStopModule(module, 0, NULL, &status, NULL);
	sceKernelUnloadModule(module);
	/* the job's results, file by file, are the answer */
	for (k = 0; k < flash_job->count; k++)
		if (flash_job->files[k].result != RP2_FLASH_DONE)
			return -1;
	return 0;
}

/* ----- what the screens show */

/* the settings against the newest backup, at start and after a backup */
static void auto_check(void)
{
	char names[RP2_BACKUPS_MAX][RP2_BACKUP_NAME], folder[64];
	int count;

	view.check = CHECK_RUNNING;
	present();
	sceKernelWaitSema(space_lock, 1, NULL);
	count = rp2_backups(&device, names, RP2_BACKUPS_MAX);
	if (!count)
		view.check = CHECK_NO_BACKUP;
	else
	{
		snprintf(view.newest, sizeof(view.newest), "%s", names[0]);
		snprintf(folder, sizeof(folder), "ms0:/BACKUP/%s", names[0]);
		if (rp2_restore_check(&device, folder, &plan, space + RP2_REPLY_HEADROOM, sizeof(space) - RP2_REPLY_HEADROOM))
			view.check = CHECK_UNREADABLE;
		else
		{
			view.check = plan.differ ? CHECK_DIFFERS : CHECK_MATCHES;
			view.check_differ = plan.differ;
		}
	}
	sceKernelSignalSema(space_lock, 1);
}

static void start_network(void)
{
	SceUID thread;

	if (net_state == -2 || (net_started && net_state != -1))
		return;
	if (net_started)
		net_down();
	net_state = 0;
	net_started = 1;
	thread = sceKernelCreateThread("rp2", server_thread, 0x18, 0x10000, PSP_THREAD_ATTR_USER, NULL);
	if (thread < 0 || sceKernelStartThread(thread, 0, NULL) < 0)
		net_state = -1;
	else
		server_id = thread;
}

static void run_backup(void)
{
	size_t length;

	view.backup.phase = 1;
	view.backup.done = 0;
	present();
	sceKernelWaitSema(space_lock, 1, NULL);
	rp2_backup(&device, space + RP2_REPLY_HEADROOM, sizeof(space) - RP2_REPLY_HEADROOM, &length);
	sceKernelSignalSema(space_lock, 1);
	view.backup.result = backup_result;
	view.backup.phase = backup_result.done == 1 ? 2 : 3;
}

static void run_check(void)
{
	char folder[64];

	snprintf(folder, sizeof(folder), "ms0:/BACKUP/%s", view.restore.names[view.restore.selected]);
	sceKernelWaitSema(space_lock, 1, NULL);
	rp2_restore_check(&device, folder, &plan, space + RP2_REPLY_HEADROOM, sizeof(space) - RP2_REPLY_HEADROOM);
	sceKernelSignalSema(space_lock, 1);
	view.restore.plan = &plan;
	view.restore.hold = 0;
	view.screen = SCREEN_RESTORE_CHECK;
}

static void run_restore(void)
{
	size_t length;

	view.screen = SCREEN_RESTORE_WORK;
	present();
	restoring = 1;
	sceKernelWaitSema(space_lock, 1, NULL);
	/* the settings as they are now, backed up first: a restore that goes
	wrong can be undone from that backup. No backup, no restore */
	if (rp2_backup(&device, space + RP2_REPLY_HEADROOM, sizeof(space) - RP2_REPLY_HEADROOM, &length) ||
		backup_result.done != 1 || backup_result.failed)
		view.restore.result = -2;
	else
		view.restore.result = rp2_restore(&device, &plan, &job, space + RP2_REPLY_HEADROOM,
			sizeof(space) - RP2_REPLY_HEADROOM);
	sceKernelSignalSema(space_lock, 1);
	restoring = 0;
	view.screen = SCREEN_RESTORE_DONE;
}

/* ----- the Wi-Fi check: what the firmware says about the switch, the chip
and connection 1 (its name and security type only: never its key) */

static void wifi_gather(void)
{
	unsigned char mac[8];
	netData data;

	memset(mac, 0, sizeof(mac));
	view.wifi.chip = sceWlanGetEtherAddr(mac) >= 0 && (mac[0] | mac[1] | mac[2] | mac[3] | mac[4] | mac[5]) ? 1 : 0;
	snprintf(view.wifi.vendor, sizeof(view.wifi.vendor), "%02X:%02X:%02X", mac[0], mac[1], mac[2]);
	view.wifi.power = sceWlanDevIsPowerOn() > 0;
	/* the first saved network, whatever its number */
	for (net_index = 1; net_index <= 32 && sceUtilityCheckNetParam(net_index) != 0; net_index++)
		;
	if (net_index > 32)
		net_index = 0;
	view.wifi.saved = net_index > 0;
	view.wifi.index = net_index;
	view.wifi.ssid[0] = 0;
	snprintf(view.wifi.security, sizeof(view.wifi.security), "?");
	if (view.wifi.saved)
	{
		memset(&data, 0, sizeof(data));
		if (sceUtilityGetNetParam(net_index, PSP_NETPARAM_SSID, &data) == 0)
			snprintf(view.wifi.ssid, sizeof(view.wifi.ssid), "%.32s", data.asString);
		memset(&data, 0, sizeof(data));
		if (sceUtilityGetNetParam(net_index, PSP_NETPARAM_SECURE, &data) == 0)
			snprintf(view.wifi.security, sizeof(view.wifi.security), "%s",
				data.asUint == 0 ? "open" : data.asUint == 1 ? "WEP" : "WPA");
	}
}

/* the switch, ten times a second, into the strip the check draws */
static void wifi_sample(unsigned long long now_us)
{
	static unsigned long long next;
	int on = sceWlanGetSwitchState() == 1;

	if (now_us < next)
		return;
	next = now_us + 100000;
	if (view.wifi.samples && view.wifi.history[WIFI_HISTORY - 1] != on)
		view.wifi.changes++;
	memmove(view.wifi.history, view.wifi.history + 1, WIFI_HISTORY - 1);
	view.wifi.history[WIFI_HISTORY - 1] = (unsigned char)on;
	view.wifi.samples++;
}

static void wifi_update(void)
{
	int k;

	view.wifi.steps = join.count;
	for (k = 0; k < join.count; k++)
	{
		view.wifi.step[k].state = join.step[k].state;
		view.wifi.step[k].event = join.step[k].event;
		view.wifi.step[k].error = join.step[k].error;
		view.wifi.step[k].ms = join.step[k].ms;
	}
	view.wifi.error = join.error;
	view.wifi.test = !net_started ? 0 : net_state == 2 ? 2 : net_state == -1 ? -1 : 1;
	view.wifi.strength = join.strength;
	view.wifi.channel = join.channel;
	snprintf(view.wifi.ip, sizeof(view.wifi.ip), "%s", join.ip);
}

/* the check as text on the Memory Stick, to read on a PC without Wi-Fi. The
network's name is shortened and the chip's address halved: it may be shared */
static void wifi_report(void)
{
	static char text[3072];
	char stamp[24] = "", verdict[200];
	SceUID file;
	int k, at, length = (int)strlen(view.wifi.ssid);

	psp_stamp(NULL, stamp, sizeof(stamp));
	screens_wifi_verdict(&view, verdict, sizeof(verdict));
	at = snprintf(text, sizeof(text),
		"RemotePilot PSP Wi-Fi check, %s (PSP clock)\r\nfirmware %s\r\n\r\n"
		"WLAN switch now: %s; %d change%s over %d readings (ten a second)\r\n"
		"Wi-Fi chip: %s (address %s:..), power %s\r\n"
		"network (first saved, number %d): %s%.2s%s (%d characters), security %s\r\n"
		"join test: %s\r\n",
		stamp, device.firmware, view.connect.wlan == 1 ? "ON" : view.connect.wlan == 0 ? "OFF" : "unknown",
		view.wifi.changes, view.wifi.changes == 1 ? "" : "s", view.wifi.samples,
		view.wifi.chip ? "answers" : "no answer", view.wifi.vendor, view.wifi.power ? "on" : "off",
		view.wifi.index, view.wifi.saved ? "set up, \"" : "not set up", view.wifi.saved ? view.wifi.ssid : "",
		view.wifi.saved ? "...\"" : "", length, view.wifi.security,
		view.wifi.test == 2 ? "joined" : view.wifi.test == -1 ? "stopped" : view.wifi.test == 1 ? "running" : "not run");
	for (k = 0; k < view.wifi.steps && at < (int)sizeof(text) - 200; k++)
		at += snprintf(text + at, sizeof(text) - (size_t)at, "  %6.1f s  %s (event %d, error %08X)\r\n",
			view.wifi.step[k].ms / 1000.0f, screens_apctl_state(view.wifi.step[k].state), view.wifi.step[k].event,
			(unsigned int)view.wifi.step[k].error);
	if (view.wifi.test == 2)
		at += snprintf(text + at, sizeof(text) - (size_t)at, "signal %d%%, channel %d\r\n", view.wifi.strength,
			view.wifi.channel);
	at += snprintf(text + at, sizeof(text) - (size_t)at, "last firmware error: %08X\r\n\r\n%s\r\n",
		(unsigned int)view.wifi.error, verdict);
	file = sceIoOpen(WIFI_REPORT, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_TRUNC, 0777);
	if (file >= 0)
	{
		int ok = sceIoWrite(file, text, (SceSize)at) == at;

		sceIoClose(file);
		snprintf(view.wifi.report, sizeof(view.wifi.report), ok ? "%s" : "couldn't write %s", WIFI_REPORT);
	}
	else
		snprintf(view.wifi.report, sizeof(view.wifi.report), "couldn't write %s", WIFI_REPORT);
}

static void update_connect(void)
{
	view.connect.wlan = sceWlanGetSwitchState();
	view.connect.net = net_state;
	snprintf(view.connect.address, sizeof(view.connect.address), "%s", address_text);
	view.connect.port = config.port;
	view.connect.served = served;
	view.connect.refused = refused;
	snprintf(view.connect.last, sizeof(view.connect.last), "%s", last_kind);
	view.connect.buttons = remote_buttons;
}

/* one frame's buttons, newly pressed, moving between the screens */
static void step(unsigned int pressed, unsigned int held, unsigned int held_here, unsigned long long now_us)
{
	static unsigned long long hold_from, restart_at;

	switch (view.screen)
	{
	case SCREEN_HOME:
		if (pressed & PSP_CTRL_TRIANGLE)
		{
			view.screen = SCREEN_BACKUP;
			view.backup.phase = 0;
		}
		else if (pressed & PSP_CTRL_SQUARE)
		{
			sceKernelWaitSema(space_lock, 1, NULL);
			view.restore.count = rp2_backups(&device, view.restore.names, RP2_BACKUPS_MAX);
			sceKernelSignalSema(space_lock, 1);
			view.restore.selected = 0;
			view.screen = SCREEN_RESTORE_PICK;
		}
		else if (pressed & PSP_CTRL_CROSS)
		{
			view.screen = SCREEN_CONNECT;
			if (view.connect.wlan != 0)
				start_network();
		}
		break;
	case SCREEN_BACKUP:
		if (view.backup.phase == 0 && (pressed & PSP_CTRL_CROSS))
		{
			run_backup();
			if (view.backup.phase == 2)
			{
				auto_check();
				view.screen = SCREEN_BACKUP;
			}
		}
		else if (pressed & PSP_CTRL_CIRCLE)
			view.screen = SCREEN_HOME;
		break;
	case SCREEN_RESTORE_PICK:
		if ((pressed & PSP_CTRL_DOWN) && view.restore.selected + 1 < view.restore.count)
			view.restore.selected++;
		else if ((pressed & PSP_CTRL_UP) && view.restore.selected > 0)
			view.restore.selected--;
		else if ((pressed & PSP_CTRL_CROSS) && view.restore.count)
			run_check();
		else if (pressed & PSP_CTRL_CIRCLE)
			view.screen = SCREEN_HOME;
		break;
	case SCREEN_RESTORE_CHECK:
		/* hold ✕ for two seconds: let go and it starts over. The PSP's own ✕
		only: a restore is never confirmed from the network */
		if ((held_here & PSP_CTRL_CROSS) && !plan.error[0] && plan.differ)
		{
			if (!hold_from)
				hold_from = now_us;
			view.restore.hold = (int)((now_us - hold_from) * RESTORE_HOLD_FRAMES / 2000000);
			if (view.restore.hold >= RESTORE_HOLD_FRAMES)
			{
				hold_from = 0;
				run_restore();
				restart_at = now_us + 5000000;
			}
		}
		else
		{
			hold_from = 0;
			view.restore.hold = 0;
			if (pressed & PSP_CTRL_CIRCLE)
				view.screen = SCREEN_RESTORE_PICK;
		}
		break;
	case SCREEN_RESTORE_DONE:
		if (!view.restore.result)
		{
			/* straight to a restart, before the system writes its settings from
			memory over the restored ones */
			view.restore.countdown = now_us >= restart_at ? 0 : (int)((restart_at - now_us) / 1000000) + 1;
			if (!view.restore.countdown || (pressed & PSP_CTRL_CROSS))
			{
				present();
				scePowerRequestColdReset(0);
				sceKernelSleepThread();
			}
		}
		else if (pressed & PSP_CTRL_CIRCLE)
		{
			auto_check();
			view.screen = SCREEN_HOME;
		}
		break;
	case SCREEN_CONNECT:
		if (view.connect.wlan != 0 && !net_started)
			start_network();
		if ((pressed & PSP_CTRL_CROSS) && net_state == -1 && view.connect.wlan != 0)
			start_network();
		else if (pressed & PSP_CTRL_TRIANGLE)
		{
			wifi_gather();
			view.wifi.report[0] = 0;
			view.screen = SCREEN_WIFI;
		}
		else if (pressed & PSP_CTRL_CIRCLE)
			view.screen = SCREEN_HOME;
		break;
	case SCREEN_WIFI:
		/* a join test is the connection itself, started or started again */
		if ((pressed & PSP_CTRL_CROSS) && view.connect.wlan != 0 && net_state != -2)
			start_network();
		else if (pressed & PSP_CTRL_TRIANGLE)
		{
			wifi_gather();
			wifi_update();
			wifi_report();
		}
		else if (pressed & PSP_CTRL_CIRCLE)
			view.screen = SCREEN_CONNECT;
		break;
	default:
		break;
	}
}

int main(int argc, char **argv)
{
	static const char *const roots[] = { "ms0:/", NULL };
	static char firmware[16];
	SceUID thread;
	SceCtrlData pad;
	unsigned long long mark;
	unsigned int previous = 0;
	int frames = 0, version;
	char *slash;

	thread = sceKernelCreateThread("exit", callback_thread, 0x11, 0x1000, 0, NULL);
	if (thread >= 0)
		sceKernelStartThread(thread, 0, NULL);
	main_thread = sceKernelGetThreadId();
	space_lock = sceKernelCreateSema("rp2 space", 0, 1, 1, NULL);
	scePowerSetClockFrequency(333, 333, 166);
	sceCtrlSetSamplingMode(PSP_CTRL_MODE_DIGITAL);
	started_us = sceKernelGetSystemTimeWide();

	/* the kernel helper sits beside the EBOOT */
	snprintf(helper_path, sizeof(helper_path), "%s", argc > 0 && argv[0] ? argv[0] : "ms0:/PSP/GAME/REMOTEPILOT/EBOOT.PBP");
	slash = strrchr(helper_path, '/');
	snprintf(slash ? slash + 1 : helper_path, sizeof(helper_path) - (size_t)(slash ? slash + 1 - helper_path : 0),
		"rp_flash.prx");
	version = sceKernelDevkitVersion();
	snprintf(firmware, sizeof(firmware), "%d.%d%d", (version >> 24) & 0xff, (version >> 16) & 0xff, (version >> 8) & 0xff);

	drawn = malloc(VRAM_STRIDE * UI_H * 4);
	backdrop = malloc(UI_W * UI_H * 4);
	if (!drawn || !backdrop)
	{
		sceKernelExitGame();
		return 0;
	}
	ui_background_make(backdrop);
	sceDisplaySetMode(0, UI_W, UI_H);

	memset(&device, 0, sizeof(device));
	device.context = &device;
	device.label = "RemotePilot PSP";
	device.config_path = CONFIG_PATH;
	device.config_path_old = CONFIG_PATH_OLD;
	device.roots = roots;
	device.log_path = LOG_PATH;
	device.frame = psp_frame;
	device.list = psp_list;
	device.read = psp_read;
	device.input = psp_input;
	device.perf = psp_perf;
	device.report = psp_report;
	device.state = "companion";
	device.now_ms = psp_now_ms;
	device.make_folder = psp_make_folder;
	device.write_new = psp_write_new;
	device.stamp = psp_stamp;
	device.backup_result = &backup_result;
	device.firmware = firmware;
	device.progress = psp_progress;
	device.flash_restore = psp_flash_restore;
	platform.context = &device;
	platform.recv = psp_recv;
	platform.send = psp_send;
	platform.random = psp_random;
	platform.hmac_sha256 = psp_hmac;
	platform.act = rp2_act;
	platform.hold = psp_hold;

	memset(&view, 0, sizeof(view));
	view.screen = SCREEN_HOME;
	view.connect.wlan = -1;
	/* the saved network's name, for the screens to say instead of a number */
	wifi_gather();
	if (config_load() < 0)
		net_state = -2;
	else
		device.app_id = config.app_id;
	auto_check();

	mark = (unsigned long long)sceKernelGetSystemTimeWide();
	while (running)
	{
		unsigned long long now = (unsigned long long)sceKernelGetSystemTimeWide();
		unsigned int here = 0, buttons;

		if (sceCtrlPeekBufferPositive(&pad, 1) > 0)
			here = pad.Buttons;
		buttons = here | remote_held();
		update_connect();
		wifi_sample(now);
		wifi_update();
		step(buttons & ~previous, buttons, here, now);
		previous = buttons;
		present();
		frames++;
		if (now - mark >= 1000000)
		{
			loop_fps = frames * 1e6 / (double)(now - mark);
			frames = 0;
			mark = now;
		}
	}
	memset(config.token, 0, sizeof(config.token));
	/* the server thread ends within a request's timeouts; the network is
	taken down only after it has, and otherwise left to the firmware, which
	unloads it at exit anyway: quitting never waits on it */
	if (net_started)
	{
		SceUInt wait = 1500000;

		if (server_id < 0 || sceKernelWaitThreadEnd(server_id, &wait) >= 0)
			net_down();
	}
	sceKernelExitGame();
	return 0;
}
