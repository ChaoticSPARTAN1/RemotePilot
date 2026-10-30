/* rp2_backup.c - the PSP's system settings backup (rp2_actions.h, rp2_backup).

flash1:/ holds the PSP's settings: the registry (date and time, nickname,
theme choices, and the network connections with their Wi-Fi passwords) and an
installed custom theme (vsh/theme/custom_theme.dat). A settings reset loses
them, and a theme whose original file is gone can't be had again. This copies
them into a new folder on the Memory Stick, where the viewer can fetch and
check them over the files action.

Nothing on flash1 is opened for writing. On the stick it makes ms0:/BACKUP
and one new flash1-<stamp> folder inside it, and never writes into a folder
that was already there. Bounded: 64 folders, 256 files, 16 MiB, and every
copy's path within what rp2_path_allowed lets the viewer fetch. */
#include "rp2_actions.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

void p2p_sha256(const void *data, int size, unsigned char *digest);

#define SOURCE "flash1:/"
#define ROOT "ms0:/BACKUP"
#define THEME "vsh/theme/custom_theme.dat"
#define WALLPAPER "vsh/theme/wallpaper.bmp"
#define MAX_FOLDERS 64
#define MAX_FILES 256
#define MAX_TOTAL (16ul * 1024 * 1024)
#define MAX_RELATIVE 120
#define ENTRY_ROOM 400 /* one file's manifest line, with the closing fields */

static struct rp2_entry entries[256];
static char folders[MAX_FOLDERS][MAX_RELATIVE + 1]; /* relative to SOURCE; "" is SOURCE itself */

struct json
{
	char *out;
	size_t at, size;
};

static void add(struct json *json, const char *format, ...)
{
	va_list args;
	int length;

	va_start(args, format);
	length = vsnprintf(json->out + json->at, json->size - json->at, format, args);
	va_end(args);
	/* the room checks before each file keep this from happening */
	if (length > 0 && (size_t)length < json->size - json->at)
		json->at += (size_t)length;
}

static int same_text(const char *a, const char *b)
{
	for (; *a && *b; a++, b++)
		if ((*a | 32) != (*b | 32))
			return 0;
	return !*a && !*b;
}

static void hex(const unsigned char *digest, char *out)
{
	static const char digits[] = "0123456789abcdef";
	int k;

	for (k = 0; k < 32; k++)
	{
		out[2 * k] = digits[digest[k] >> 4];
		out[2 * k + 1] = digits[digest[k] & 15];
	}
	out[64] = 0;
}

/* one file: read it whole, write the copy, read the copy back and compare */
static int copy_file(const struct rp2_device *device, const char *source, const char *target, unsigned char *buffer,
                     size_t buffer_size, unsigned long room, unsigned char digest[32], unsigned long *size)
{
	unsigned long total = 0, again_total = 0;
	unsigned char check[32];
	long got, again;

	got = device->read(device->context, source, 0, buffer, (unsigned long)buffer_size, &total);
	if (got < 0 || (unsigned long)got != total || total > room)
		return -1;
	p2p_sha256(buffer, (int)got, digest);
	if (device->write_new(device->context, target, buffer, (unsigned long)got))
		return -1;
	memset(buffer, 0, (size_t)got);
	again = device->read(device->context, target, 0, buffer, (unsigned long)buffer_size, &again_total);
	if (again != got || again_total != total)
		return -1;
	p2p_sha256(buffer, (int)again, check);
	if (memcmp(digest, check, 32))
		return -1;
	*size = (unsigned long)got;
	return 0;
}

int rp2_backup(const struct rp2_device *device, unsigned char *space, size_t size, size_t *length)
{
	struct rp2_backup_result result;
	struct json json;
	char stamp[24] = "", source[sizeof(SOURCE) + MAX_RELATIVE + 1], target[200];
	const char *error = NULL;
	unsigned char *buffer = space + RP2_BACKUP_MANIFEST, digest[32];
	size_t buffer_size = size > RP2_BACKUP_MANIFEST ? size - RP2_BACKUP_MANIFEST : 0;
	int head = 0, tail = 0, k, attempt;

	*length = 0;
	if (buffer_size < 4096)
		return -1;
	memset(&result, 0, sizeof(result));
	json.out = (char *)space;
	json.at = 0;
	json.size = RP2_BACKUP_MANIFEST;

	if (!device->list || !device->read || !device->make_folder || !device->write_new || !device->stamp)
		error = "this device can't make backups";
	else if (device->list(device->context, SOURCE, entries, 1) < 0)
		error = "flash1:/ can't be read here";
	else if (device->stamp(device->context, stamp, sizeof(stamp)) || device->make_folder(device->context, ROOT))
		error = "ms0:/BACKUP can't be made";
	else
	{
		/* a folder that wasn't there before: never one written earlier */
		for (attempt = 1; attempt <= 9; attempt++)
		{
			snprintf(result.folder, sizeof(result.folder), ROOT "/flash1-%s%s%.0d", stamp, attempt > 1 ? "-" : "",
				attempt > 1 ? attempt : 0);
			if (device->list(device->context, result.folder, entries, 1) < 0 &&
				device->make_folder(device->context, result.folder) == 0)
				break;
		}
		if (attempt > 9)
		{
			result.folder[0] = 0;
			error = "no new folder name is free";
		}
	}
	add(&json, "{\"folder\":\"%s\",\"source\":\"" SOURCE "\",\"made\":\"%s\",\"firmware\":\"%s\",\"files\":[",
		error ? "" : result.folder, stamp, device->firmware ? device->firmware : "");

	if (!error)
		folders[tail++][0] = 0;
	while (head < tail)
	{
		const char *relative = folders[head++];
		int count;

		snprintf(source, sizeof(source), SOURCE "%.*s", MAX_RELATIVE, relative);
		count = device->list(device->context, source, entries, (int)(sizeof(entries) / sizeof(entries[0])));
		if (count < 0)
		{
			result.failed++;
			continue;
		}
		for (k = 0; k < count; k++)
		{
			const char *name = entries[k].name;
			char path[MAX_RELATIVE + 1];
			unsigned long copied = 0;
			int fits;

			if (!strcmp(name, ".") || !strcmp(name, ".."))
				continue;
			fits = snprintf(path, sizeof(path), "%s%s%s", relative, *relative ? "/" : "", name) < (int)sizeof(path);
			/* the copy's path must be one the viewer may fetch */
			if (!fits || snprintf(target, sizeof(target), "%s/%s", result.folder, path) >= (int)sizeof(target) ||
				!rp2_path_allowed(device, target))
			{
				result.failed++;
				continue;
			}
			if (entries[k].directory)
			{
				if (tail >= MAX_FOLDERS || device->make_folder(device->context, target))
					result.failed++;
				else
					strcpy(folders[tail++], path);
				continue;
			}
			snprintf(source, sizeof(source), SOURCE "%.*s", MAX_RELATIVE, path);
			if (device->progress)
				device->progress(device->context, path, result.files);
			if (result.files >= MAX_FILES || json.size - json.at < ENTRY_ROOM ||
				copy_file(device, source, target, buffer, buffer_size, MAX_TOTAL - result.bytes, digest, &copied))
			{
				result.failed++;
				continue;
			}
			{
				char text[65];

				hex(digest, text);
				add(&json, "%s{\"path\":\"%s\",\"size\":%lu,\"sha256\":\"%s\"}", result.files ? "," : "", path, copied,
					text);
			}
			result.files++;
			result.bytes += copied;
			if (same_text(path, THEME))
				result.theme = 1;
			if (same_text(path, WALLPAPER))
				result.wallpaper = 1;
		}
	}
	if (!error && !result.files)
		error = "no file could be copied";
	add(&json, "],\"failed\":%d,\"bytes\":%lu,\"theme\":%s,\"error\":\"%s\"}", result.failed, result.bytes,
		result.theme ? "true" : "false", error ? error : "");

	/* the manifest beside the copies, for checking them later from the card */
	if (result.folder[0])
	{
		snprintf(target, sizeof(target), "%s/manifest.json", result.folder);
		if (device->write_new(device->context, target, json.out, (unsigned long)json.at) && !error)
			error = "manifest.json can't be written";
	}
	result.done = error ? -1 : 1;
	snprintf(result.error, sizeof(result.error), "%s", error ? error : "");
	if (device->backup_result)
		*device->backup_result = result;
	*length = json.at;
	return error ? -1 : 0;
}
