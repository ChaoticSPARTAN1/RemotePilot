/* rp2_restore.c - the PSP's system settings restore (rp2_actions.h).

A backup made by rp2_backup.c is put back on flash1 only after:
  - its manifest reads and every copy on the stick matches it (SHA-256);
  - it was made on the same firmware (a backup without a firmware note, from
    an older RemotePilot, is allowed: the screen says it wasn't recorded);
  - something actually differs from flash1 now.
Only the files that differ are written, the registry last, and each is read
back (rp2_flash_copy.c). Then flash1 is compared with the backup again.

No RP2 action reaches this: the device's own screen asks for it, with a held
button. Nothing on flash0 is ever touched. */
#include "rp2_actions.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void p2p_sha256(const void *data, int size, unsigned char *digest);

/* ms0:/BACKUP's entries: the backups among them are counted and listed (a
remote backup stops at RP2_BACKUPS_MAX of them) */
static struct rp2_entry entries[256];

static int backup_name(const char *name)
{
	size_t k, size = strlen(name);

	if (size < 22 || size >= RP2_BACKUP_NAME || strncmp(name, "flash1-", 7))
		return 0;
	for (k = 7; k < size; k++)
		if (!((name[k] >= '0' && name[k] <= '9') || name[k] == '-'))
			return 0;
	return 1;
}

static int newest_first(const void *a, const void *b)
{
	return strcmp((const char *)b, (const char *)a);
}

int rp2_backups(const struct rp2_device *device, char names[][RP2_BACKUP_NAME], int max)
{
	int count, k, found = 0;

	if (!device->list)
		return 0;
	count = device->list(device->context, "ms0:/BACKUP", entries, (int)(sizeof(entries) / sizeof(entries[0])));
	for (k = 0; k < count && found < max; k++)
		if (entries[k].directory && backup_name(entries[k].name))
			snprintf(names[found++], RP2_BACKUP_NAME, "%s", entries[k].name);
	qsort(names, (size_t)found, RP2_BACKUP_NAME, newest_first);
	return found;
}

/* "key":"value" after at, into out; the end of the value, or NULL */
static const char *json_text(const char *at, const char *end, const char *key, char *out, size_t size)
{
	size_t length = strlen(key), k = 0;

	for (; at + length + 4 < end; at++)
		if (at[0] == '"' && !strncmp(at + 1, key, length) && at[length + 1] == '"' && at[length + 2] == ':' &&
			at[length + 3] == '"')
		{
			for (at += length + 4; at < end && *at != '"'; at++)
			{
				if (k + 1 >= size || *at == '\\')
					return NULL;
				out[k++] = *at;
			}
			out[k] = 0;
			return at < end ? at : NULL;
		}
	return NULL;
}

static const char *json_number(const char *at, const char *end, const char *key, unsigned long *value)
{
	size_t length = strlen(key);
	char *stop;

	for (; at + length + 3 < end; at++)
		if (at[0] == '"' && !strncmp(at + 1, key, length) && at[length + 1] == '"' && at[length + 2] == ':')
		{
			*value = strtoul(at + length + 3, &stop, 10);
			return stop > at + length + 3 ? stop : NULL;
		}
	return NULL;
}

static int unhex(const char *text, unsigned char *out)
{
	int k;

	for (k = 0; k < 64; k++)
	{
		int c = text[k], v = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1;

		if (v < 0)
			return -1;
		if (k & 1)
			out[k / 2] |= (unsigned char)v;
		else
			out[k / 2] = (unsigned char)(v << 4);
	}
	return text[64] ? -1 : 0;
}

/* the manifest's files, each object in order: path, size, sha256 */
static int parse(struct rp2_restore_plan *plan, const char *text, size_t size)
{
	const char *end = text + size, *at = strstr(text, "\"files\":["), *close;
	char hex[72];

	if (!at || !json_text(text, at, "made", plan->made, sizeof(plan->made)))
		return -1;
	if (!json_text(text, at, "firmware", plan->firmware, sizeof(plan->firmware)))
		plan->firmware[0] = 0;
	close = strstr(at, "]");
	if (!close)
		return -1;
	plan->count = 0;
	while ((at = strstr(at, "{\"path\"")) && at < close)
	{
		if (plan->count >= RP2_FLASH_FILES)
			return -1;
		if (!(at = json_text(at, close, "path", plan->files[plan->count].path, sizeof(plan->files[0].path))) ||
			!(at = json_number(at, close, "size", &plan->files[plan->count].size)) ||
			!(at = json_text(at, close, "sha256", hex, sizeof(hex))) || unhex(hex, plan->files[plan->count].sha256) ||
			strstr(plan->files[plan->count].path, "..") || plan->files[plan->count].path[0] == '/')
			return -1;
		plan->count++;
	}
	(void)end;
	return plan->count ? 0 : -1;
}

static int same_hash(const struct rp2_device *device, const char *path, unsigned long size,
                     const unsigned char sha256[32], unsigned char *buffer, size_t buffer_size)
{
	unsigned long total = 0;
	unsigned char digest[32];
	long got = device->read(device->context, path, 0, buffer, (unsigned long)buffer_size, &total);

	if (got < 0)
		return -1;
	if ((unsigned long)got != total || total != size)
		return 0;
	p2p_sha256(buffer, (int)got, digest);
	return memcmp(digest, sha256, 32) == 0;
}

int rp2_restore_check(const struct rp2_device *device, const char *folder, struct rp2_restore_plan *plan,
                      unsigned char *space, size_t size)
{
	char path[200];
	unsigned long total = 0;
	long got;
	int k;

	memset(plan, 0, sizeof(*plan));
	snprintf(plan->folder, sizeof(plan->folder), "%s", folder);
	if (!device->read || size < RP2_FLASH_MAX_FILE + 1)
	{
		snprintf(plan->error, sizeof(plan->error), "this device can't restore");
		return -1;
	}
	snprintf(path, sizeof(path), "%s/manifest.json", folder);
	got = device->read(device->context, path, 0, space, (unsigned long)size - 1, &total);
	if (got <= 0 || (unsigned long)got != total)
	{
		snprintf(plan->error, sizeof(plan->error), "its manifest.json can't be read");
		return -1;
	}
	space[got] = 0;
	if (parse(plan, (const char *)space, (size_t)got))
	{
		snprintf(plan->error, sizeof(plan->error), "its manifest.json isn't one RemotePilot wrote");
		return -1;
	}
	plan->same_firmware = !plan->firmware[0] ? -1 : device->firmware && !strcmp(plan->firmware, device->firmware);
	plan->intact = 1;
	for (k = 0; k < plan->count; k++)
	{
		int same;

		snprintf(path, sizeof(path), "%s/%s", folder, plan->files[k].path);
		if (device->progress)
			device->progress(device->context, plan->files[k].path, k);
		if (plan->files[k].size > RP2_FLASH_MAX_FILE ||
			same_hash(device, path, plan->files[k].size, plan->files[k].sha256, space, size) != 1)
			plan->intact = 0;
		snprintf(path, sizeof(path), "flash1:/%s", plan->files[k].path);
		same = same_hash(device, path, plan->files[k].size, plan->files[k].sha256, space, size);
		plan->files[k].state = same == 1 ? RP2_SAME : same == 0 ? RP2_DIFFERS : RP2_MISSING_NOW;
		if (same != 1)
			plan->differ++;
	}
	if (!plan->intact)
		snprintf(plan->error, sizeof(plan->error), "a copy on the stick differs from its manifest");
	else if (plan->same_firmware == 0)
		snprintf(plan->error, sizeof(plan->error), "made on firmware %s, this PSP has %s", plan->firmware,
			device->firmware ? device->firmware : "?");
	else if (!device->flash_restore)
		snprintf(plan->error, sizeof(plan->error), "this device can't write its settings");
	return plan->error[0] ? -1 : 0;
}

static int registry(const char *path)
{
	return !strncmp(path, "registry/", 9);
}

int rp2_restore(const struct rp2_device *device, struct rp2_restore_plan *plan, struct rp2_flash_job *job,
                unsigned char *space, size_t size)
{
	int pass, k;

	if (plan->error[0] || !plan->intact || plan->same_firmware == 0 || !device->flash_restore)
		return -1;
	if (!plan->differ)
		return 0;
	memset(job, 0, sizeof(*job));
	job->magic = RP2_FLASH_MAGIC;
	job->buffer = space;
	job->buffer_size = (unsigned int)(size > RP2_FLASH_MAX_FILE ? RP2_FLASH_MAX_FILE : size);
	/* everything else first, the registry last: if a write stops partway,
	the settings themselves are the last thing changed */
	for (pass = 0; pass < 2; pass++)
		for (k = 0; k < plan->count; k++)
		{
			struct rp2_flash_file *file;

			if (plan->files[k].state == RP2_SAME || registry(plan->files[k].path) != pass)
				continue;
			file = &job->files[job->count++];
			snprintf(file->from, sizeof(file->from), "%s/%s", plan->folder, plan->files[k].path);
			snprintf(file->to, sizeof(file->to), "flash1:/%s", plan->files[k].path);
			file->size = (unsigned int)plan->files[k].size;
			memcpy(file->sha256, plan->files[k].sha256, 32);
			/* not done until the writer says so: a writer that never ran
			(its module didn't start) leaves this, a failure */
			file->result = RP2_FLASH_PENDING;
		}
	if (device->progress)
		device->progress(device->context, "writing", 0);
	if (device->flash_restore(device->context, job))
		return -1;
	/* and flash1 as it is now, from the start */
	{
		char folder[64];

		snprintf(folder, sizeof(folder), "%s", plan->folder);
		if (rp2_restore_check(device, folder, plan, space, size) || plan->differ)
			return -1;
	}
	return 0;
}
