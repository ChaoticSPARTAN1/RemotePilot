/* screens.h - RemotePilot PSP's guided screens, drawn from a view: what the
companion knows right now. platform_psp.c fills the view and moves between
screens on the buttons; render_screens.c draws sample views on a PC.

One idea throughout, as in the 3DS companion: each screen says what is
happening, shows the one thing to do next with its button, and what comes
after. */
#ifndef SCREENS_H
#define SCREENS_H

#include "ui.h"
#include "../rp2_actions.h"

enum screen
{
	SCREEN_HOME,
	SCREEN_BACKUP,          /* backup.phase: 0 about, 1 copying, 2 done, 3 failed */
	SCREEN_RESTORE_PICK,
	SCREEN_RESTORE_CHECK,   /* the chosen backup checked, the hold to confirm */
	SCREEN_RESTORE_WORK,
	SCREEN_RESTORE_DONE,    /* restore.result: 0 restored, < 0 stopped */
	SCREEN_CONNECT,
	SCREEN_WIFI             /* the Wi-Fi check */
};

#define WIFI_HISTORY 120      /* the switch, read ten times a second */
#define WIFI_STEPS 12

enum auto_check { CHECK_RUNNING, CHECK_MATCHES, CHECK_DIFFERS, CHECK_NO_BACKUP, CHECK_UNREADABLE };

struct view
{
	enum screen screen;
	unsigned int frame;           /* 60 a second: the animations' clock */

	/* home: the settings checked against the newest backup at start */
	enum auto_check check;
	char newest[RP2_BACKUP_NAME];
	int check_differ;

	struct
	{
		int phase, done;
		char what[128];
		struct rp2_backup_result result;
	} backup;

	struct
	{
		char names[RP2_BACKUPS_MAX][RP2_BACKUP_NAME];
		int count, selected;
		const struct rp2_restore_plan *plan;
		int hold;                 /* frames ✕ has been held: 120 confirms */
		int done, total;          /* files checked or written */
		int result;
		int countdown;            /* seconds to the restart */
	} restore;

	struct
	{
		int wlan;                 /* the WLAN switch: 1 on, 0 off, -1 unknown */
		int net;                  /* 0 not started, 1 joining, 2 up, -1 couldn't join, -2 no pairing */
		char address[32];
		unsigned int port, served, refused;
		char last[24];
		unsigned int buttons;
	} connect;

	/* the Wi-Fi check: the switch, the chip, connection 1 and a join */
	struct
	{
		unsigned char history[WIFI_HISTORY];  /* 1 on, 0 off, oldest first */
		int samples, changes;
		int chip;                 /* the chip gave its address: 1 yes, 0 no */
		char vendor[12];          /* the address's first half only: "00:1F:A7" */
		int power;                /* sceWlanDevIsPowerOn */
		int saved, index;         /* a network is saved; the first one's number */
		char ssid[34], security[8];
		int test;                 /* the join: 0 not run, 1 running, 2 got an address, -1 stopped */
		int steps;
		struct { int state, event, error; unsigned int ms; } step[WIFI_STEPS];
		int error;                /* the last error the firmware gave */
		int strength, channel;
		char ip[16];
		char report[48];          /* where the report was saved, or "" */
	} wifi;
};

#define RESTORE_HOLD_FRAMES 120

void screens_draw(struct ui *ui, const uint32_t *background, const struct view *view);

/* what the Wi-Fi check found, in a sentence (for the screen and the report) */
void screens_wifi_verdict(const struct view *view, char *out, int size);
const char *screens_apctl_state(int state);

/* "flash1-20261029-153000" as "2026-10-29 15:30:00" */
void screens_backup_date(const char *name, char *out, int size);

#endif
