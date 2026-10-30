/*
RP_FLASH.PRX

The settings restore's writes (rp2_flash.h), the one thing RemotePilot PSP
can't do from user mode: a user-mode EBOOT may read flash1 but not write it.
The companion loads this kernel module only when the user has chosen a
backup, checked it and held the confirm button, starts it once with its job,
and unloads it.

What it does is rp2_flash_copy.c's steps, nothing else: each file read from a
checked backup under ms0:/BACKUP/flash1-..., its SHA-256 compared with the
manifest, written beside its flash1 file, read back, put in its place and
read back again. Paths are checked again here: from only
ms0:/BACKUP/flash1-..., to only flash1's settings folders, no "..". flash0 is
never opened.

Whoever loads it, it trusts nothing in user memory while it works:
- the job's address must lie wholly inside the user partition (no kernel
  address, no wrap);
- the job is copied once into this module's own memory, and only that copy
  is checked and used (a user thread changing the job meanwhile changes
  nothing here);
- the files go through a buffer this module allocates in kernel memory;
- only the per-file results are written back, to the same checked range.
*/
#include <pspkernel.h>
#include <pspiofilemgr.h>
#include <pspsysmem_kernel.h>
#include <string.h>

#include "rp2_flash.h"

PSP_MODULE_INFO("rp_flash", PSP_MODULE_KERNEL, 1, 0);
PSP_MAIN_THREAD_ATTR(0);

/* the PSP's user partition, cached addresses only */
#define USER_LOW 0x08800000u
#define USER_HIGH 0x0a000000u

static struct rp2_flash_job job;

static int user_range(const void *pointer, unsigned int size)
{
	unsigned int at = (unsigned int)pointer;

	/* aligned as well: the results are written back as words */
	return (at & 3u) == 0 && at >= USER_LOW && at < USER_HIGH && size <= USER_HIGH - at;
}

static int file_read(const char *path, unsigned char *buffer, unsigned int size)
{
	SceUID file = sceIoOpen(path, PSP_O_RDONLY, 0);
	SceOff length;
	unsigned int done = 0;

	if (file < 0)
		return -1;
	length = sceIoLseek(file, 0, PSP_SEEK_END);
	if (length < 0 || length > (SceOff)size || sceIoLseek(file, 0, PSP_SEEK_SET) != 0)
	{
		sceIoClose(file);
		return -1;
	}
	while (done < (unsigned int)length)
	{
		int got = sceIoRead(file, buffer + done, (unsigned int)length - done);

		if (got <= 0)
			break;
		done += (unsigned int)got;
	}
	sceIoClose(file);
	return done == (unsigned int)length ? (int)done : -1;
}

static int file_write(const char *path, const unsigned char *data, unsigned int size)
{
	SceUID file = sceIoOpen(path, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_TRUNC, 0777);
	unsigned int done = 0;

	if (file < 0)
		return -1;
	while (done < size)
	{
		int wrote = sceIoWrite(file, data + done, size - done);

		if (wrote <= 0)
			break;
		done += (unsigned int)wrote;
	}
	return sceIoClose(file) >= 0 && done == size ? 0 : -1;
}

static int file_remove(const char *path)
{
	return sceIoRemove(path) < 0 ? -1 : 0;
}

static int file_rename(const char *from, const char *to)
{
	return sceIoRename(from, to) < 0 ? -1 : 0;
}

/* argp: the job's address (in user memory). The results are each file's
result in the job: the companion reads those, not this return, which is
always 0 so the firmware treats the start the same either way and the
companion stops and unloads the module itself */
int module_start(SceSize args, void *argp)
{
	static const struct rp2_flash_io io = { file_read, file_write, file_remove, file_rename };
	struct rp2_flash_job *user;
	unsigned int size = RP2_FLASH_MAX_FILE;
	SceUID block = -1;
	int k;

	if (args != sizeof(user) || !argp)
		return 0;
	memcpy(&user, argp, sizeof(user));
	if (!user_range(user, sizeof(*user)))
		return 0;
	memcpy(&job, user, sizeof(job));
	/* the copy's own buffer, in kernel memory: the largest the kernel spares */
	while (size >= 256u * 1024 && (block = sceKernelAllocPartitionMemory(1, "rp_flash", PSP_SMEM_Low, size, NULL)) < 0)
		size /= 2;
	if (block < 0)
		return 0;
	job.buffer = sceKernelGetBlockHeadAddr(block);
	job.buffer_size = size;
	rp2_flash_copy(&job, &io);
	memset(job.buffer, 0, size);
	sceKernelFreePartitionMemory(block);
	/* the results, back to the range checked above */
	for (k = 0; k < job.count && k < RP2_FLASH_FILES; k++)
		user->files[k].result = job.files[k].result;
	return 0;
}

int module_stop(SceSize args, void *argp)
{
	(void)args;
	(void)argp;
	return 0;
}
