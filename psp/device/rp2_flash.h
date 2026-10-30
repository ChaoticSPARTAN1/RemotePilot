/* rp2_flash.h - a settings restore's writes to flash1, shared by the restore
(rp2_restore.c), the kernel helper that does them on the PSP (flash/main.c,
rp_flash.prx) and the simulator. rp2_flash_copy runs the same steps in both.

Each file goes from a checked backup on the Memory Stick to flash1:
  1. read the backup's copy whole and check its SHA-256 against the manifest;
  2. write it beside the flash1 file (<name>.rpnew) and read that back;
  3. put it in the old file's place (remove, rename; written in place where
     the file system won't rename), and read the result back.
The first file that fails stops the job: the rest stay as they were, and a
failure before step 3 leaves even that file whole. Paths are checked here
too, whoever asked: from only "ms0:/BACKUP/flash1-...", to only flash1's
settings folders (registry, vsh/theme, dic, net/http, gps, updater), no "..",
nothing else (never flash0). */
#ifndef RP2_FLASH_H
#define RP2_FLASH_H

#define RP2_FLASH_MAGIC 0x31465052u /* "RPF1" */
#define RP2_FLASH_FILES 32
#define RP2_FLASH_MAX_FILE (2u * 1024 * 1024)

enum rp2_flash_result
{
	RP2_FLASH_PENDING = 1,    /* not reached: an earlier file failed */
	RP2_FLASH_DONE = 0,       /* written and read back the same */
	RP2_FLASH_REFUSED = -1,   /* a path or size this never writes */
	RP2_FLASH_NO_COPY = -2,   /* the backup's copy can't be read */
	RP2_FLASH_BAD_COPY = -3,  /* the backup's copy differs from its manifest: nothing written */
	RP2_FLASH_NO_WRITE = -4,  /* the write failed */
	RP2_FLASH_BAD_WRITE = -5, /* what was written reads back different */
	RP2_FLASH_IN_TEMPORARY = -6 /* the old file is gone and the new one is checked, but only as <name>.rpnew */
};

struct rp2_flash_file
{
	char from[160];             /* "ms0:/BACKUP/flash1-.../registry/system.dreg" */
	char to[136];               /* "flash1:/registry/system.dreg" */
	unsigned int size;
	unsigned char sha256[32];
	int result;                 /* enum rp2_flash_result */
};

struct rp2_flash_job
{
	unsigned int magic;
	int count;
	unsigned char *buffer;      /* one file at a time */
	unsigned int buffer_size;
	struct rp2_flash_file files[RP2_FLASH_FILES];
};

/* the steps above, over the caller's file calls: read up to size bytes of a
whole file (its length, or < 0), and write a whole file (0 on success) */
struct rp2_flash_io
{
	int (*read)(const char *path, unsigned char *buffer, unsigned int size);
	int (*write)(const char *path, const unsigned char *data, unsigned int size);
	int (*remove)(const char *path);                   /* 0, or < 0 (also: wasn't there) */
	int (*rename)(const char *from, const char *to);   /* 0, or < 0 */
};

/* 0 when every file is RP2_FLASH_DONE */
int rp2_flash_copy(struct rp2_flash_job *job, const struct rp2_flash_io *io);

#endif
