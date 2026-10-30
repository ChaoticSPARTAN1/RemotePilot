/* rp2_actions.c - the PSP's RP2 actions (rp2_actions.h). Every answer is
bounded by the reply's capacity and the protocol's per-kind limits. */
#include "rp2_actions.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TEXT_LIMIT 65536u
#define META_LIMIT 8192u
#define LIST_MAX 256
#define PATH_MAX_LENGTH 160

static int lower(int c)
{
	return c >= 'A' && c <= 'Z' ? c + 32 : c;
}

static int same_path(const char *a, const char *b)
{
	for (; *a && *b; a++, b++)
		if (lower((unsigned char)*a) != lower((unsigned char)*b))
			return 0;
	return !*a && !*b;
}

static int prefix_of(const char *root, const char *path)
{
	size_t k;

	for (k = 0; root[k]; k++)
		if (lower((unsigned char)root[k]) != lower((unsigned char)path[k]))
			/* "ms0:/halo" itself is inside the root "ms0:/halo/" */
			return root[k] == '/' && !root[k + 1] && !path[k];
	return 1;
}

static int name_char(int c)
{
	return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
		c == ' ' || c == '_' || c == '-' || c == '.' || c == '(' || c == ')' || c == '+' || c == ',' || c == '&';
}

int rp2_path_allowed(const struct rp2_device *device, const char *path)
{
	size_t k, size = strlen(path), start = 5;
	const char *const *root;

	if (size < 5 || size > PATH_MAX_LENGTH || strncmp(path, "ms0:/", 5))
		return 0;
	/* each component: safe characters, not empty, not "." or "..", no
	leading or trailing space (FAT would strip it) */
	for (k = 5; k <= size; k++)
	{
		if (k == size || path[k] == '/')
		{
			size_t length = k - start;

			if (k == size && length == 0 && size > 5 && path[k - 1] == '/')
				return 0; /* a trailing slash */
			if (length == 0 && !(k == 5 && size == 5))
				return 0;
			if ((length == 1 && path[start] == '.') || (length == 2 && path[start] == '.' && path[start + 1] == '.'))
				return 0;
			if (length && (path[start] == ' ' || path[k - 1] == ' ' || path[k - 1] == '.'))
				return 0;
			start = k + 1;
		}
		else if (!name_char((unsigned char)path[k]))
			return 0;
	}
	if ((device->config_path && same_path(device->config_path, path)) ||
		(device->config_path_old && same_path(device->config_path_old, path)))
		return 0;
	for (root = device->roots; root && *root; root++)
		if (prefix_of(*root, path))
			return 1;
	return 0;
}

static unsigned int read_u16(const unsigned char *p)
{
	return p[0] | p[1] << 8;
}

static void put_u32(unsigned char *p, unsigned long value)
{
	p[0] = (unsigned char)value;
	p[1] = (unsigned char)(value >> 8);
	p[2] = (unsigned char)(value >> 16);
	p[3] = (unsigned char)(value >> 24);
}

/* one pixel as 8-bit B, G, R */
static void pixel(const void *pixels, int stride, int format, int x, int y, unsigned char *out)
{
	if (format == RP2_PIXEL_8888)
	{
		const unsigned char *p = (const unsigned char *)pixels + 4 * ((size_t)y * stride + x);

		out[0] = p[2];
		out[1] = p[1];
		out[2] = p[0];
		return;
	}
	{
		unsigned int v = read_u16((const unsigned char *)pixels + 2 * ((size_t)y * stride + x));
		unsigned int r, g, b;

		if (format == RP2_PIXEL_565)
		{
			r = v & 31;
			g = v >> 5 & 63;
			b = v >> 11 & 31;
			out[0] = (unsigned char)(b << 3 | b >> 2);
			out[1] = (unsigned char)(g << 2 | g >> 4);
			out[2] = (unsigned char)(r << 3 | r >> 2);
		}
		else if (format == RP2_PIXEL_5551)
		{
			r = v & 31;
			g = v >> 5 & 31;
			b = v >> 10 & 31;
			out[0] = (unsigned char)(b << 3 | b >> 2);
			out[1] = (unsigned char)(g << 3 | g >> 2);
			out[2] = (unsigned char)(r << 3 | r >> 2);
		}
		else
		{
			r = v & 15;
			g = v >> 4 & 15;
			b = v >> 8 & 15;
			out[0] = (unsigned char)(b * 17);
			out[1] = (unsigned char)(g * 17);
			out[2] = (unsigned char)(r * 17);
		}
	}
}

/* the displayed frame as a 24-bit BMP, at 1/scale size (1 or 2); 0 if it doesn't fit */
size_t rp2_bmp(const struct rp2_device *device, int scale, unsigned char *out, size_t capacity)
{
	const void *pixels;
	int stride, format, x, y;
	int width = RP2_SCREEN_WIDTH / scale, height = RP2_SCREEN_HEIGHT / scale;
	size_t row = ((size_t)width * 3 + 3) & ~(size_t)3, size = 54 + row * (size_t)height;

	if (size > capacity || !device->frame || device->frame(device->context, &pixels, &stride, &format) || !pixels ||
		stride < RP2_SCREEN_WIDTH || format < RP2_PIXEL_565 || format > RP2_PIXEL_8888)
		return 0;
	memset(out, 0, 54);
	out[0] = 'B';
	out[1] = 'M';
	put_u32(out + 2, (unsigned long)size);
	put_u32(out + 10, 54);
	put_u32(out + 14, 40);
	put_u32(out + 18, (unsigned long)width);
	put_u32(out + 22, (unsigned long)height);
	out[26] = 1;
	out[28] = 24;
	put_u32(out + 34, (unsigned long)(row * (size_t)height));
	/* bottom-up rows, as BMP stores them */
	for (y = 0; y < height; y++)
	{
		unsigned char *line = out + 54 + row * (size_t)(height - 1 - y);

		for (x = 0; x < width; x++)
			pixel(pixels, stride, format, x * scale, y * scale, line + 3 * x);
		memset(line + 3 * width, 0, row - 3 * (size_t)width);
	}
	return size;
}

/* a number after "key": in a small JSON object; 0 when found */
static int json_number(const char *json, const char *key, double *value)
{
	char pattern[24];
	const char *at;
	char *end;

	snprintf(pattern, sizeof(pattern), "\"%s\":", key);
	at = strstr(json, pattern);
	if (!at)
		return -1;
	*value = strtod(at + strlen(pattern), &end);
	/* "nan" parses, and passes every range check after: refused here */
	return end == at + strlen(pattern) || *value != *value ? -1 : 0;
}

static int json_string(const char *json, const char *key, char *out, size_t size)
{
	char pattern[24];
	const char *at;
	size_t k = 0;

	snprintf(pattern, sizeof(pattern), "\"%s\":\"", key);
	at = strstr(json, pattern);
	if (!at)
		return -1;
	for (at += strlen(pattern); *at && *at != '"'; at++)
	{
		if (k + 1 >= size)
			return -1;
		out[k++] = *at;
	}
	out[k] = 0;
	return *at == '"' ? 0 : -1;
}

/* the standard Gamepad API's buttons, as the PSP has them */
static unsigned int psp_buttons(unsigned int standard)
{
	static const unsigned int map[16] = {
		RP2_PSP_CROSS, RP2_PSP_CIRCLE, RP2_PSP_SQUARE, RP2_PSP_TRIANGLE, RP2_PSP_LTRIGGER, RP2_PSP_RTRIGGER,
		RP2_PSP_LTRIGGER, RP2_PSP_RTRIGGER, RP2_PSP_SELECT, RP2_PSP_START, 0, 0,
		RP2_PSP_UP, RP2_PSP_DOWN, RP2_PSP_LEFT, RP2_PSP_RIGHT };
	unsigned int out = 0, k;

	for (k = 0; k < 16; k++)
		if (standard & 1u << k)
			out |= map[k];
	return out;
}

static unsigned int named_button(const char *name)
{
	static const struct { const char *name; unsigned int bit; } names[] = {
		{ "CROSS", RP2_PSP_CROSS }, { "CIRCLE", RP2_PSP_CIRCLE }, { "SQUARE", RP2_PSP_SQUARE },
		{ "TRIANGLE", RP2_PSP_TRIANGLE }, { "UP", RP2_PSP_UP }, { "DOWN", RP2_PSP_DOWN }, { "LEFT", RP2_PSP_LEFT },
		{ "RIGHT", RP2_PSP_RIGHT }, { "L", RP2_PSP_LTRIGGER }, { "R", RP2_PSP_RTRIGGER },
		{ "START", RP2_PSP_START }, { "SELECT", RP2_PSP_SELECT } };
	size_t k;

	for (k = 0; k < sizeof(names) / sizeof(names[0]); k++)
		if (!strcmp(names[k].name, name))
			return names[k].bit;
	return 0;
}

static int nub(double axis)
{
	int value;

	if (axis < -1 || axis > 1)
		return -1;
	value = 128 + (int)(axis * 127.0 + (axis < 0 ? -0.5 : 0.5));
	return value < 0 ? 0 : value > 255 ? 255 : value;
}

static int text_reply(struct rp2_reply *reply, const char *text)
{
	size_t size = strlen(text);

	if (size > reply->capacity)
		return -1;
	memcpy(reply->data, text, size);
	reply->length = size;
	return 0;
}

static int act_files(struct rp2_device *device, const char *path, struct rp2_reply *reply)
{
	static struct rp2_entry entries[LIST_MAX];
	size_t limit = reply->capacity < TEXT_LIMIT ? reply->capacity : TEXT_LIMIT, at;
	int count, k, shown = 0, skipped = 0;
	char *out = (char *)reply->data;

	if (!device->list || !rp2_path_allowed(device, path))
		return -1;
	count = device->list(device->context, path, entries, LIST_MAX);
	if (count < 0)
		return -1;
	/* room kept at the end for the closing fields (under 48 bytes) */
	if (limit < 512)
		return -1;
	at = (size_t)snprintf(out, limit, "{\"path\":\"%s\",\"entries\":[", path);
	for (k = 0; k < count; k++)
	{
		char child[PATH_MAX_LENGTH + 66];
		const char *name = entries[k].name;
		size_t room = limit - at - 48;
		int length;

		length = snprintf(child, sizeof(child), "%s%s%s", path, path[strlen(path) - 1] == '/' ? "" : "/", name);
		if (length < 0 || (size_t)length >= sizeof(child) || !strcmp(name, ".") || !strcmp(name, "..") ||
			!rp2_path_allowed(device, child))
		{
			skipped++;
			continue;
		}
		length = snprintf(out + at, room, "%s{\"name\":\"%s\",\"dir\":%s,\"size\":%lu}", shown ? "," : "",
			name, entries[k].directory ? "true" : "false", entries[k].directory ? 0ul : entries[k].size);
		if (length < 0 || (size_t)length >= room)
			break;
		at += (size_t)length;
		shown++;
	}
	at += (size_t)snprintf(out + at, limit - at, "],\"skipped\":%d,\"truncated\":%s}", skipped + (count - k),
		k < count ? "true" : "false");
	if (at >= limit)
		return -1;
	reply->length = at;
	return 0;
}

static int act_file(struct rp2_device *device, const char *path, struct rp2_reply *reply)
{
	unsigned long total = 0;
	long got;

	if (!device->read || !rp2_path_allowed(device, path))
		return -1;
	got = device->read(device->context, path, 0, reply->data, (unsigned long)reply->capacity, &total);
	/* whole files only: a file larger than one reply is refused, not cut */
	if (got < 0 || (unsigned long)got != total)
		return -1;
	reply->length = (size_t)got;
	return 0;
}

static int act_log(struct rp2_device *device, struct rp2_reply *reply)
{
	unsigned long total = 0, want = reply->capacity < TEXT_LIMIT ? (unsigned long)reply->capacity : TEXT_LIMIT;
	long got;

	if (!device->read || !device->log_path)
		return -1;
	/* the size first, then the last 64 KiB */
	if (device->read(device->context, device->log_path, 0, reply->data, 0, &total) < 0)
		return -1;
	got = device->read(device->context, device->log_path, total > want ? total - want : 0, reply->data, want, &total);
	if (got < 0)
		return -1;
	reply->length = (size_t)got;
	return 0;
}

int rp2_act(void *context, const char *kind, const unsigned char *body, size_t size, struct rp2_reply *reply)
{
	struct rp2_device *device = context;
	const char *text = (const char *)body;
	char line[META_LIMIT];

	/* every body is text: one with a NUL inside would be read as something
	shorter than what was signed (rp2_serve ends the body with a NUL) */
	if (strlen(text) != size)
		return -1;
	if (!strcmp(kind, "ping"))
		return 0;
	if (!strcmp(kind, "meta"))
	{
		snprintf(line, sizeof(line),
			"{\"schemaVersion\":2,\"appId\":\"%s\",\"label\":\"%s\",\"state\":\"%s\",\"captureSequence\":%u}",
			device->app_id ? device->app_id : "", device->label ? device->label : "PSP",
			device->state ? device->state : "running", device->capture_sequence);
		return text_reply(reply, line);
	}
	if (!strcmp(kind, "perf"))
	{
		double fps, frame_ms, work_ms;

		if (!device->perf || device->perf(device->context, &fps, &frame_ms, &work_ms) || fps < 0 || frame_ms < 0 ||
			work_ms < 0)
			return -1;
		snprintf(line, sizeof(line), "{\"fps\":%.2f,\"frameMs\":%.2f,\"workMs\":%.2f,\"timestampMs\":%llu}", fps,
			frame_ms, work_ms, device->now_ms ? device->now_ms(device->context) : 0ull);
		return text_reply(reply, line);
	}
	if (!strcmp(kind, "shot"))
	{
		reply->length = rp2_bmp(device, 1, reply->data, reply->capacity);
		return reply->length ? 0 : -1;
	}
	if (!strcmp(kind, "stream"))
	{
		size_t image;

		if (reply->capacity < 8)
			return -1;
		/* half size: 98 KB a frame instead of 392 KB on the PSP's Wi-Fi */
		image = rp2_bmp(device, 2, reply->data + 8, reply->capacity - 8);
		if (!image)
			return -1;
		put_u32(reply->data, (unsigned long)image);
		put_u32(reply->data + 4, 0);
		reply->length = 8 + image;
		return 0;
	}
	if (!strcmp(kind, "log"))
		return act_log(device, reply);
	if (!strcmp(kind, "report"))
	{
		size_t limit = reply->capacity < TEXT_LIMIT ? reply->capacity : TEXT_LIMIT;

		if (!device->report)
			return -1;
		reply->length = device->report(device->context, (char *)reply->data, limit);
		return reply->length && reply->length <= limit ? 0 : -1;
	}
	if (!strcmp(kind, "backup"))
	{
		/* its JSON answers even a failed backup: the viewer shows why. A remote
		backup stops at RP2_BACKUPS_MAX on the stick, so the network can't fill
		it (16 MiB at most each); the console's own △ isn't limited */
		static char names[RP2_BACKUPS_MAX][RP2_BACKUP_NAME];

		if (size || !device->write_new || rp2_backups(device, names, RP2_BACKUPS_MAX) >= RP2_BACKUPS_MAX)
			return -1;
		rp2_backup(device, reply->data, reply->capacity, &reply->length);
		return reply->length ? 0 : -1;
	}
	if (!strcmp(kind, "files"))
		return act_files(device, text, reply);
	if (!strcmp(kind, "file"))
		return act_file(device, text, reply);
	if (!strcmp(kind, "gamepad") || !strcmp(kind, "input"))
	{
		double buttons = 0, lx = 0, ly = 0, frames = 1;
		char name[16];
		unsigned int mask;

		if (!device->input)
			return -1;
		if (!strcmp(kind, "input"))
		{
			if (json_string(text, "button", name, sizeof(name)) || json_number(text, "frames", &frames) ||
				!(mask = named_button(name)) || frames < 1 || frames > 30)
				return -1;
			device->input(device->context, mask, 128, 128, (int)frames);
			return text_reply(reply, "ok");
		}
		if (json_number(text, "buttons", &buttons) || buttons < 0 || buttons > 65535 ||
			json_number(text, "lx", &lx) || json_number(text, "ly", &ly) || json_number(text, "frames", &frames) ||
			nub(lx) < 0 || nub(ly) < 0 || frames < 1 || frames > 8)
			return -1;
		device->input(device->context, psp_buttons((unsigned int)buttons), nub(lx), nub(ly), (int)frames);
		return text_reply(reply, "ok");
	}
	return -1;
}
