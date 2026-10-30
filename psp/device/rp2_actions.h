/* rp2_actions.h - the PSP's RP2 actions (ping, meta, perf, shot, stream, log,
report, files, file, gamepad, input, backup), over a small device interface
that the PSP (platform_psp.c) and the desktop simulator (platform_host.c) each
fill.

Files are read-only, with one exception: backup (rp2_backup.c) copies the
PSP's system settings (flash1:/) into a new folder under ms0:/BACKUP and
writes nothing else. Paths are "ms0:/..." on both; the simulator maps them to
a local folder. The device config (it holds the pairing token) is never
listed or read, whatever the path. */
#ifndef RP2_ACTIONS_H
#define RP2_ACTIONS_H

#include <stddef.h>
#include "rp2_device.h"
#include "rp2_flash.h"

#define RP2_SCREEN_WIDTH 480
#define RP2_SCREEN_HEIGHT 272

/* PSP display pixel formats (pspdisplay.h's numbering) */
enum rp2_pixel_format { RP2_PIXEL_565 = 0, RP2_PIXEL_5551 = 1, RP2_PIXEL_4444 = 2, RP2_PIXEL_8888 = 3 };

struct rp2_entry
{
	char name[64];
	int directory;
	unsigned long size;
};

/* what the last settings backup did, for the device's own screen */
struct rp2_backup_result
{
	int done;                 /* 1 made, -1 failed, 0 none yet */
	char folder[64];          /* "ms0:/BACKUP/flash1-20261029-153000" */
	char error[64];           /* why it failed, when done is -1 */
	int files, failed, theme; /* theme: the custom theme file was among them */
	int wallpaper;             /* and a wallpaper set from a picture */
	unsigned long bytes;
};

struct rp2_device
{
	void *context;
	const char *app_id;        /* the config's app_id, echoed by meta */
	const char *label;         /* "RemotePilot PSP", or a game's own name */
	const char *config_path;   /* never listed or read */
	const char *config_path_old; /* an earlier place for it, also never listed or read, or NULL */
	const char *const *roots;  /* allowed path prefixes, NULL-terminated, e.g. "ms0:/halo/" */
	const char *log_path;      /* the log kind's file */
	/* the displayed frame: pixels, its stride in pixels, its format; 0 on success */
	int (*frame)(void *context, const void **pixels, int *stride, int *format);
	/* a directory's entries, up to max; returns the count or < 0 */
	int (*list)(void *context, const char *path, struct rp2_entry *entries, int max);
	/* up to size bytes of a file from offset; returns bytes read or < 0; *total is the file's size */
	long (*read)(void *context, const char *path, unsigned long offset, void *buffer, unsigned long size,
	             unsigned long *total);
	/* remote input: PSP button mask (psp_ctrl.h's), analog nub 0..255, held for frames */
	void (*input)(void *context, unsigned int buttons, int lx, int ly, int frames);
	/* the frame rate and times the build measures; 0 when none */
	int (*perf)(void *context, double *fps, double *frame_ms, double *work_ms);
	/* free-form report lines (system, storage, build), into out */
	size_t (*report)(void *context, char *out, size_t size);
	unsigned int capture_sequence;  /* bumped by the device's own Bug It action */
	const char *state;              /* "menu", "playing", ... */
	unsigned long long (*now_ms)(void *context);
	/* the settings backup; NULL where there is none. A folder (0 when made or
	already there), a new file with these bytes (< 0 if one exists), and the
	local time as "YYYYMMDD-HHMMSS" */
	int (*make_folder)(void *context, const char *path);
	int (*write_new)(void *context, const char *path, const void *data, unsigned long size);
	int (*stamp)(void *context, char *out, size_t size);
	struct rp2_backup_result *backup_result; /* filled by each backup, or NULL */
	const char *firmware;    /* "6.61": recorded in each backup, checked before a restore */
	/* called as a backup or restore goes (a file's path, files done), or NULL */
	void (*progress)(void *context, const char *what, int done);
	/* writes a restore's files to flash1 (rp2_flash.h), or NULL where restore
	isn't offered; 0 when every file was written and read back the same */
	int (*flash_restore)(void *context, struct rp2_flash_job *job);
};

/* rp2_platform.act for these actions; context is a struct rp2_device */
int rp2_act(void *context, const char *kind, const unsigned char *body, size_t size, struct rp2_reply *reply);

/* the settings backup (rp2_backup.c): copies every file under flash1:/ into a
new ms0:/BACKUP/flash1-<stamp> folder, reads each copy back to check it, and
writes manifest.json there (each file's path, size and SHA-256). The same
JSON goes to the start of space, its length to *length; the rest of space
holds one file at a time (at least 64 KiB + the largest file). Returns 0
when a folder was made, < 0 when nothing could be (the JSON says why). Not
reentrant: one backup at a time */
#define RP2_BACKUP_MANIFEST 65536u
int rp2_backup(const struct rp2_device *device, unsigned char *space, size_t size, size_t *length);

/* ----- the settings restore (rp2_restore.c), on the device only: no RP2
action starts one, so nothing on the network can write the settings */

#define RP2_BACKUPS_MAX 16
#define RP2_BACKUP_NAME 40

/* the backups in ms0:/BACKUP (flash1-... folder names), newest first */
int rp2_backups(const struct rp2_device *device, char names[][RP2_BACKUP_NAME], int max);

enum rp2_restore_state { RP2_SAME = 0, RP2_DIFFERS = 1, RP2_MISSING_NOW = 2 };

struct rp2_restore_plan
{
	char folder[64];          /* "ms0:/BACKUP/flash1-..." */
	char made[24], firmware[16];
	int count;
	struct
	{
		char path[124];       /* relative to flash1:/ */
		unsigned long size;
		unsigned char sha256[32];
		int state;            /* enum rp2_restore_state: flash1 now against the backup */
	} files[RP2_FLASH_FILES];
	int intact;               /* every copy on the stick matches the manifest */
	int same_firmware;        /* 1 same, 0 different (refused), -1 not recorded */
	int differ;               /* files flash1 has differently now, or lacks */
	char error[64];           /* why it can't be restored, or "" */
};

/* reads a backup's manifest, checks its copies on the stick and compares
flash1 with it. 0 when it could be restored (error empty) */
int rp2_restore_check(const struct rp2_device *device, const char *folder, struct rp2_restore_plan *plan,
                      unsigned char *space, size_t size);

/* writes the files that differ back to flash1 (registry last) through
device->flash_restore, then compares again. 0 when flash1 now matches the
backup; the caller restarts the PSP straight after, before the system writes
its own settings from memory over the restored ones */
int rp2_restore(const struct rp2_device *device, struct rp2_restore_plan *plan, struct rp2_flash_job *job,
                unsigned char *space, size_t size);

/* exported for the host tests */
int rp2_path_allowed(const struct rp2_device *device, const char *path);
size_t rp2_bmp(const struct rp2_device *device, int scale, unsigned char *out, size_t capacity);

/* PSP button bits (pspctrl.h) */
#define RP2_PSP_SELECT 0x000001u
#define RP2_PSP_START 0x000008u
#define RP2_PSP_UP 0x000010u
#define RP2_PSP_RIGHT 0x000020u
#define RP2_PSP_DOWN 0x000040u
#define RP2_PSP_LEFT 0x000080u
#define RP2_PSP_LTRIGGER 0x000100u
#define RP2_PSP_RTRIGGER 0x000200u
#define RP2_PSP_TRIANGLE 0x001000u
#define RP2_PSP_CIRCLE 0x002000u
#define RP2_PSP_CROSS 0x004000u
#define RP2_PSP_SQUARE 0x008000u

#endif
