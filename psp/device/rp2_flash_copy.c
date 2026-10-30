/* rp2_flash_copy.c - a restore's writes to flash1 (rp2_flash.h). Built into
the kernel helper (flash/main.c) and the simulator, so the steps the PSP takes
are the ones the tests run. Only the kernel's own string calls are used.

The kernel helper calls this on its own copy of the job, in kernel memory,
with a kernel buffer: nothing here is read from user memory while it runs. */
#include "rp2_flash.h"

#include <string.h>

void p2p_sha256(const void *data, int size, unsigned char *digest);

/* the only places a restore may write: flash1's settings, never anything else
on it, never another device */
static const char *const destinations[] = {
	"flash1:/registry/", "flash1:/vsh/theme/", "flash1:/dic/", "flash1:/net/http/", "flash1:/gps/",
	"flash1:/updater/", NULL
};
#define TEMPORARY ".rpnew"

static int starts(const char *text, const char *prefix)
{
	return strncmp(text, prefix, strlen(prefix)) == 0;
}

/* NUL inside the field, no "..", no backslash, no colon after the device */
static int clean_path(const char *path, unsigned int size, unsigned int device_length)
{
	unsigned int k;

	for (k = 0; k < size && path[k]; k++)
	{
		if (path[k] == '\\' || (k >= device_length && path[k] == ':') || (unsigned char)path[k] < 32)
			return 0;
		if (path[k] == '.' && k + 1 < size && path[k + 1] == '.')
			return 0;
	}
	return k < size;
}

static int allowed(const struct rp2_flash_file *file, unsigned int buffer_size)
{
	int k, destination = 0;

	if (!clean_path(file->from, sizeof(file->from), 5) || !clean_path(file->to, sizeof(file->to), 7) ||
		!starts(file->from, "ms0:/BACKUP/flash1-") || file->size > RP2_FLASH_MAX_FILE || file->size > buffer_size ||
		strlen(file->to) + sizeof(TEMPORARY) > sizeof(file->to))
		return 0;
	for (k = 0; destinations[k]; k++)
		if (starts(file->to, destinations[k]) && file->to[strlen(destinations[k])])
			destination = 1;
	return destination;
}

/* the file at path is size bytes with this SHA-256 */
static int same(const struct rp2_flash_io *io, const char *path, unsigned char *buffer, unsigned int buffer_size,
                unsigned int size, const unsigned char sha256[32])
{
	unsigned char digest[32];
	int got;

	memset(buffer, 0, size);
	got = io->read(path, buffer, buffer_size);
	if (got < 0 || (unsigned int)got != size)
		return 0;
	p2p_sha256(buffer, got, digest);
	return memcmp(digest, sha256, 32) == 0;
}

int rp2_flash_copy(struct rp2_flash_job *job, const struct rp2_flash_io *io)
{
	unsigned char digest[32];
	int k, failed = 0;

	if (!job || job->magic != RP2_FLASH_MAGIC || job->count < 1 || job->count > RP2_FLASH_FILES || !job->buffer)
		return -1;
	for (k = 0; k < job->count; k++)
		job->files[k].result = RP2_FLASH_PENDING;
	/* every path first: a job with one bad path writes nothing */
	for (k = 0; k < job->count; k++)
		if (!allowed(&job->files[k], job->buffer_size))
		{
			job->files[k].result = RP2_FLASH_REFUSED;
			return -1;
		}
	for (k = 0; k < job->count && !failed; k++)
	{
		struct rp2_flash_file *file = &job->files[k];
		char temporary[sizeof(file->to) + sizeof(TEMPORARY)];
		int got = io->read(file->from, job->buffer, job->buffer_size);

		if (got < 0 || (unsigned int)got != file->size)
		{
			file->result = RP2_FLASH_NO_COPY;
			failed = 1;
			continue;
		}
		p2p_sha256(job->buffer, got, digest);
		if (memcmp(digest, file->sha256, 32))
		{
			file->result = RP2_FLASH_BAD_COPY;
			failed = 1;
			continue;
		}
		/* the new file beside the old one, checked, then put in its place: a
		failure before the swap leaves the old file whole */
		/* memcpy, not strcpy and strcat: gcc joins those into stpcpy, which the
		kernel's string library (SysclibForKernel) doesn't have */
		memcpy(temporary, file->to, strlen(file->to));
		memcpy(temporary + strlen(file->to), TEMPORARY, sizeof(TEMPORARY));
		io->remove(temporary);
		if (io->write(temporary, job->buffer, file->size))
		{
			io->remove(temporary);
			file->result = RP2_FLASH_NO_WRITE;
			failed = 1;
			continue;
		}
		if (!same(io, temporary, job->buffer, job->buffer_size, file->size, file->sha256))
		{
			io->remove(temporary);
			file->result = RP2_FLASH_BAD_WRITE;
			failed = 1;
			continue;
		}
		io->remove(file->to);
		if (io->rename(temporary, file->to))
		{
			/* a file system that won't rename: written in place instead, from
			the checked copy (read back into the buffer above), and if even
			that fails, the rename once more; failing all three, the checked
			copy stays as <name>.rpnew and says so */
			if (io->write(file->to, job->buffer, file->size) && io->rename(temporary, file->to))
			{
				file->result = RP2_FLASH_IN_TEMPORARY;
				failed = 1;
				continue;
			}
			io->remove(temporary);
		}
		if (!same(io, file->to, job->buffer, job->buffer_size, file->size, file->sha256))
		{
			file->result = RP2_FLASH_BAD_WRITE;
			failed = 1;
			continue;
		}
		file->result = RP2_FLASH_DONE;
	}
	return failed ? -1 : 0;
}
