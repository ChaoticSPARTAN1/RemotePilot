/* platform_host.c - a desktop stand-in for the PSP, for testing the viewer and
the device code without a console.

	rp2_sim --config <device config> --root <folder used as ms0:/>
	        [--flash1 <folder used as flash1:/>] [--once]
	rp2_sim --root <ms0 folder> --flash1 <flash1 folder> --check|--restore <ms0:/BACKUP/flash1-...>
	rp2_sim --root <ms0 folder> --flash1 <flash1 folder> --backup

The second form runs the settings restore (rp2_restore.c, rp2_flash_copy.c)
as the PSP's screen would, without a network, and prints what it found.

It runs the same rp2_device.c, rp2_actions.c and rp2_backup.c the PSP runs,
listening on 127.0.0.1 only. The screen is a moving test pattern drawn in the
PSP's 16-bit 565 format, so the BMP conversion is exercised; files come from
--root, and the settings backup reads --flash1 (without it, backup fails as
on a PSP that can't read its flash1). */
#include "rp2_device.h"
#include "rp2_actions.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <bcrypt.h>
typedef SOCKET socket_t;
#define CLOSE closesocket
#else
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>
typedef int socket_t;
#define CLOSE close
#endif

void p2p_hmac_sha256(const unsigned char *key, int key_size, const void *data, int size, unsigned char *digest);

static char root[512], flash1[512];
static struct rp2_backup_result backup_result;
static unsigned short screen[512 * RP2_SCREEN_HEIGHT];
static unsigned long frames_drawn;
static unsigned int last_buttons;
static int last_lx = 128, last_ly = 128;

static unsigned long long now_ms(void *context)
{
	(void)context;
#ifdef _WIN32
	return GetTickCount64();
#else
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (unsigned long long)t.tv_sec * 1000 + (unsigned long long)t.tv_nsec / 1000000;
#endif
}

/* "ms0:/a/b" -> "<root>/a/b" (the path was checked by rp2_path_allowed), and
the backup's "flash1:/a" -> "<flash1>/a"; an unmapped flash1 is a folder
that isn't there */
static void local_path(const char *path, char *out, size_t size)
{
	if (!strncmp(path, "flash1:/", 8))
		snprintf(out, size, "%s/%s", flash1[0] ? flash1 : "<no flash1>", path + 8);
	else
		snprintf(out, size, "%s/%s", root, path + 5);
}

static int sim_recv(void *context, int socket, void *buffer, size_t size)
{
	(void)context;
	return recv((socket_t)socket, buffer, (int)size, 0);
}

static int sim_send(void *context, int socket, const void *buffer, size_t size)
{
	(void)context;
	return send((socket_t)socket, buffer, (int)(size > 65536 ? 65536 : size), 0);
}

static int sim_random(void *context, unsigned char *out, size_t size)
{
	(void)context;
#ifdef _WIN32
	return BCryptGenRandom(NULL, out, (ULONG)size, BCRYPT_USE_SYSTEM_PREFERRED_RNG) == 0 ? 0 : -1;
#else
	FILE *f = fopen("/dev/urandom", "rb");
	size_t got = f ? fread(out, 1, size, f) : 0;

	if (f)
		fclose(f);
	return got == size ? 0 : -1;
#endif
}

static void sim_hmac(const unsigned char *key, size_t key_size, const unsigned char *data, size_t size,
                     unsigned char digest[32])
{
	p2p_hmac_sha256(key, (int)key_size, data, (int)size, digest);
}

/* a moving pattern in 565: bars, a sweeping column and the held buttons */
static int sim_frame(void *context, const void **pixels, int *stride, int *format)
{
	int x, y;
	unsigned long t = frames_drawn++;

	(void)context;
	for (y = 0; y < RP2_SCREEN_HEIGHT; y++)
		for (x = 0; x < RP2_SCREEN_WIDTH; x++)
		{
			unsigned int r = (unsigned int)(x * 31 / RP2_SCREEN_WIDTH), g = (unsigned int)(y * 63 / RP2_SCREEN_HEIGHT);
			unsigned int b = (unsigned int)((x + y + t * 6) % 64 < 32 ? 24 : 6);

			if ((unsigned long)x == (t * 8) % RP2_SCREEN_WIDTH)
				r = 31, g = 63, b = 31;
			/* the nub's position as a dot, the buttons as a bar */
			if (abs(x - (last_lx * RP2_SCREEN_WIDTH / 256)) < 4 && abs(y - (last_ly * RP2_SCREEN_HEIGHT / 256)) < 4)
				r = 31, g = 0, b = 0;
			if (y > RP2_SCREEN_HEIGHT - 12 && (last_buttons >> (x / 20)) & 1)
				r = 0, g = 63, b = 0;
			screen[y * 512 + x] = (unsigned short)(r | g << 5 | b << 11);
		}
	*pixels = screen;
	*stride = 512;
	*format = RP2_PIXEL_565;
	return 0;
}

static int sim_list(void *context, const char *path, struct rp2_entry *entries, int max)
{
	char local[700];
	int count = 0;

	(void)context;
	local_path(path, local, sizeof(local));
#ifdef _WIN32
	{
		WIN32_FIND_DATAA data;
		HANDLE find;
		char pattern[720];

		snprintf(pattern, sizeof(pattern), "%s/*", local);
		find = FindFirstFileA(pattern, &data);
		if (find == INVALID_HANDLE_VALUE)
			return -1;
		do
		{
			if (strlen(data.cFileName) >= sizeof(entries[0].name) || count >= max)
				continue;
			strcpy(entries[count].name, data.cFileName);
			entries[count].directory = (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
			entries[count].size = data.nFileSizeLow;
			count++;
		} while (FindNextFileA(find, &data));
		FindClose(find);
	}
#else
	{
		DIR *dir = opendir(local);
		struct dirent *entry;

		if (!dir)
			return -1;
		while ((entry = readdir(dir)) && count < max)
		{
			char child[1024];
			struct stat st;

			if (strlen(entry->d_name) >= sizeof(entries[0].name))
				continue;
			snprintf(child, sizeof(child), "%s/%s", local, entry->d_name);
			if (stat(child, &st))
				continue;
			strcpy(entries[count].name, entry->d_name);
			entries[count].directory = S_ISDIR(st.st_mode);
			entries[count].size = (unsigned long)st.st_size;
			count++;
		}
		closedir(dir);
	}
#endif
	return count;
}

static long sim_read(void *context, const char *path, unsigned long offset, void *buffer, unsigned long size,
                     unsigned long *total)
{
	char local[700];
	FILE *f;
	long length, got;

	(void)context;
	local_path(path, local, sizeof(local));
	f = fopen(local, "rb");
	if (!f)
		return -1;
	if (fseek(f, 0, SEEK_END) || (length = ftell(f)) < 0 || fseek(f, (long)offset, SEEK_SET))
	{
		fclose(f);
		return -1;
	}
	*total = (unsigned long)length;
	got = (long)fread(buffer, 1, size, f);
	fclose(f);
	return got;
}

static void sim_input(void *context, unsigned int buttons, int lx, int ly, int frames)
{
	(void)context;
	last_buttons = buttons;
	last_lx = lx;
	last_ly = ly;
	printf("input: buttons %06x nub %d,%d for %d frames\n", buttons, lx, ly, frames);
	fflush(stdout);
}

static int sim_make_folder(void *context, const char *path)
{
	char local[700];

	(void)context;
	local_path(path, local, sizeof(local));
#ifdef _WIN32
	if (CreateDirectoryA(local, NULL) || GetLastError() == ERROR_ALREADY_EXISTS)
		return 0;
	return -1;
#else
	return mkdir(local, 0777) == 0 || errno == EEXIST ? 0 : -1;
#endif
}

static int sim_write_new(void *context, const char *path, const void *data, unsigned long size)
{
	char local[700];
	FILE *f;
	int ok;

	(void)context;
	local_path(path, local, sizeof(local));
	if ((f = fopen(local, "rb")))
	{
		fclose(f);
		return -1;
	}
	if (!(f = fopen(local, "wb")))
		return -1;
	ok = fwrite(data, 1, size, f) == size;
	return fclose(f) == 0 && ok ? 0 : -1;
}

static int sim_stamp(void *context, char *out, size_t size)
{
	time_t now = time(NULL);
	struct tm *local = localtime(&now);

	(void)context;
	return local && strftime(out, size, "%Y%m%d-%H%M%S", local) ? 0 : -1;
}

/* the restore's file calls (rp2_flash.h), as the PSP's kernel helper makes
them: whole files, by their device paths */
static int sim_flash_read(const char *path, unsigned char *buffer, unsigned int size)
{
	char local[700];
	FILE *f;
	long length;
	int got;

	local_path(path, local, sizeof(local));
	if (!(f = fopen(local, "rb")))
		return -1;
	if (fseek(f, 0, SEEK_END) || (length = ftell(f)) < 0 || (unsigned long)length > size || fseek(f, 0, SEEK_SET))
	{
		fclose(f);
		return -1;
	}
	got = (int)fread(buffer, 1, (size_t)length, f);
	fclose(f);
	return got == length ? got : -1;
}

static int sim_flash_write(const char *path, const unsigned char *data, unsigned int size)
{
	char local[700];
	FILE *f;
	int ok;

	local_path(path, local, sizeof(local));
	if (!(f = fopen(local, "wb")))
		return -1;
	ok = fwrite(data, 1, size, f) == size;
	return fclose(f) == 0 && ok ? 0 : -1;
}

static int sim_flash_remove(const char *path)
{
	char local[700];

	local_path(path, local, sizeof(local));
	return remove(local) == 0 ? 0 : -1;
}

static int sim_flash_rename(const char *from, const char *to)
{
	char local_from[700], local_to[700];

	local_path(from, local_from, sizeof(local_from));
	local_path(to, local_to, sizeof(local_to));
	return rename(local_from, local_to) == 0 ? 0 : -1;
}

static int sim_flash_restore(void *context, struct rp2_flash_job *job)
{
	static const struct rp2_flash_io io = { sim_flash_read, sim_flash_write, sim_flash_remove, sim_flash_rename };

	(void)context;
	return rp2_flash_copy(job, &io);
}

static int sim_perf(void *context, double *fps, double *frame_ms, double *work_ms)
{
	(void)context;
	*fps = 29.5;
	*frame_ms = 33.9;
	*work_ms = 28.1;
	return 0;
}

static size_t sim_report(void *context, char *out, size_t size)
{
	int length;

	(void)context;
	length = snprintf(out, size, "RemotePilot PSP simulator\nmodel: desktop stand-in (no console)\nframes drawn: %lu\n"
		"root: ms0:/ is a local test folder\n", frames_drawn);
	return length > 0 && (size_t)length < size ? (size_t)length : 0;
}

static void device_fill(struct rp2_device *device)
{
	static const char *const roots[] = { "ms0:/", NULL };

	memset(device, 0, sizeof(*device));
	device->context = device;
	device->label = "PSP simulator";
	device->config_path = "ms0:/remotepilot/remotepilot.cfg";
	device->config_path_old = "ms0:/halo/remotepilot.cfg";
	device->roots = roots;
	device->log_path = "ms0:/halo/log/log.txt";
	device->frame = sim_frame;
	device->list = sim_list;
	device->read = sim_read;
	device->input = sim_input;
	device->perf = sim_perf;
	device->report = sim_report;
	device->state = "simulated";
	device->now_ms = now_ms;
	device->make_folder = sim_make_folder;
	device->write_new = sim_write_new;
	device->stamp = sim_stamp;
	device->backup_result = &backup_result;
	device->firmware = "6.61";
	device->flash_restore = sim_flash_restore;
}

/* --backup: the manifest, as the backup action answers it */
static int backup_run(void)
{
	static unsigned char space[4 * 1024 * 1024];
	struct rp2_device device;
	size_t length;
	int result;

	device_fill(&device);
	result = rp2_backup(&device, space, sizeof(space), &length);
	fwrite(space, 1, length, stdout);
	printf("\n");
	return result ? 1 : 0;
}

/* --check / --restore: one line of JSON-ish text a test can read */
static int restore_run(const char *folder, int write)
{
	static unsigned char space[4 * 1024 * 1024];
	static struct rp2_restore_plan plan;
	static struct rp2_flash_job job;
	struct rp2_device device;
	int result, k;

	device_fill(&device);
	result = rp2_restore_check(&device, folder, &plan, space, sizeof(space));
	if (write && !result)
		result = rp2_restore(&device, &plan, &job, space, sizeof(space));
	printf("result=%d intact=%d firmware=%d differ=%d error=%s\n", result, plan.intact, plan.same_firmware, plan.differ,
		plan.error);
	for (k = 0; k < plan.count; k++)
		printf("file %s state=%d\n", plan.files[k].path, plan.files[k].state);
	for (k = 0; write && k < job.count; k++)
		printf("wrote %s result=%d\n", job.files[k].to, job.files[k].result);
	return result ? 1 : 0;
}

int main(int argc, char **argv)
{
	static unsigned char space[RP2_REPLY_HEADROOM + 4 * 1024 * 1024];
	const char *config_file = NULL, *check = NULL, *restore = NULL;
	int backup = 0;
	char text[1024];
	struct rp2_config config;
	struct rp2_device device;
	struct rp2_platform platform;
	struct rp2_reply reply;
	struct sockaddr_in address;
	socket_t listener;
	FILE *f;
	size_t size;
	int k, once = 0, one = 1;

	for (k = 1; k < argc; k++)
	{
		if (!strcmp(argv[k], "--config") && k + 1 < argc)
			config_file = argv[++k];
		else if (!strcmp(argv[k], "--root") && k + 1 < argc)
			snprintf(root, sizeof(root), "%s", argv[++k]);
		else if (!strcmp(argv[k], "--flash1") && k + 1 < argc)
			snprintf(flash1, sizeof(flash1), "%s", argv[++k]);
		else if (!strcmp(argv[k], "--once"))
			once = 1;
		else if (!strcmp(argv[k], "--check") && k + 1 < argc)
			check = argv[++k];
		else if (!strcmp(argv[k], "--restore") && k + 1 < argc)
			restore = argv[++k];
		else if (!strcmp(argv[k], "--backup"))
			backup = 1;
	}
	if (backup)
		return backup_run();
	if (check || restore)
		return restore_run(check ? check : restore, restore != NULL);
	if (!config_file || !root[0] || !(f = fopen(config_file, "rb")))
	{
		fprintf(stderr, "usage: rp2_sim --config <device config> --root <folder used as ms0:/> "
			"[--flash1 <folder used as flash1:/>] [--once]\n");
		return 2;
	}
	size = fread(text, 1, sizeof(text) - 1, f);
	fclose(f);
	if (rp2_config_parse(text, size, &config) || !config.session_on)
	{
		fprintf(stderr, "rp2_sim: the config is invalid or its session is off\n");
		return 2;
	}
#ifdef _WIN32
	{
		WSADATA wsa;

		WSAStartup(MAKEWORD(2, 2), &wsa);
	}
#endif
	device_fill(&device);
	device.app_id = config.app_id;
	memset(&platform, 0, sizeof(platform));
	platform.context = NULL;
	platform.recv = sim_recv;
	platform.send = sim_send;
	platform.random = sim_random;
	platform.hmac_sha256 = sim_hmac;
	platform.act = rp2_act;
	reply.data = space + RP2_REPLY_HEADROOM;
	reply.capacity = sizeof(space) - RP2_REPLY_HEADROOM;

	listener = socket(AF_INET, SOCK_STREAM, 0);
	setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, (const char *)&one, sizeof(one));
	memset(&address, 0, sizeof(address));
	address.sin_family = AF_INET;
	address.sin_port = htons((unsigned short)config.port);
	address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	if (bind(listener, (struct sockaddr *)&address, sizeof(address)) || listen(listener, 2))
	{
		fprintf(stderr, "rp2_sim: can't listen on 127.0.0.1:%u\n", config.port);
		return 1;
	}
	printf("rp2_sim: %s on 127.0.0.1:%u, ms0:/ = %s\n", config.app_id, config.port, root);
	fflush(stdout);
	for (;;)
	{
		struct sockaddr_in peer;
		socklen_t peer_size = sizeof(peer);
		socket_t client = accept(listener, (struct sockaddr *)&peer, &peer_size);
		int result;

		if (client == (socket_t)-1)
			continue;
		if (!rp2_private_ipv4(ntohl(peer.sin_addr.s_addr)))
		{
			CLOSE(client);
			continue;
		}
		{
#ifdef _WIN32
			DWORD timeout = 3000;
#else
			struct timeval timeout = { 3, 0 };
#endif
			setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, (const char *)&timeout, sizeof(timeout));
			setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, (const char *)&timeout, sizeof(timeout));
		}
		device.context = &device;
		platform.context = &device;
		result = rp2_serve(&platform, &config, (int)client, &reply);
		printf("rp2_sim: %s %s (%lu bytes)\n", result ? "refused" : "answered", result ? "-" : reply.kind,
			(unsigned long)(result ? 0 : reply.length));
		fflush(stdout);
		CLOSE(client);
		if (once)
			break;
	}
	CLOSE(listener);
	return 0;
}
