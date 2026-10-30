/* render_screens.c - draws RemotePilot PSP's screens (screens.c) on a PC, from
sample views, into 480x272 PPM images: to look at them and test them without a
console. psp/tools/render_screens.py builds and runs it.

	render_screens <output folder> */
#include "screens.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t pixels[UI_W * UI_H], background[UI_W * UI_H];

static void save(const char *folder, const char *name, const struct view *view)
{
	struct ui ui = { pixels, UI_W };
	char path[600];
	FILE *f;
	int k;

	screens_draw(&ui, background, view);
	snprintf(path, sizeof(path), "%s/%s.ppm", folder, name);
	f = fopen(path, "wb");
	if (!f)
		exit(1);
	fprintf(f, "P6\n%d %d\n255\n", UI_W, UI_H);
	for (k = 0; k < UI_W * UI_H; k++)
	{
		unsigned char rgb[3] = { (unsigned char)pixels[k], (unsigned char)(pixels[k] >> 8),
			(unsigned char)(pixels[k] >> 16) };

		fwrite(rgb, 1, 3, f);
	}
	fclose(f);
}

int main(int argc, char **argv)
{
	static struct view v;
	static struct rp2_restore_plan plan;
	const char *out = argc > 1 ? argv[1] : ".";

	ui_background_make(background);
	memset(&v, 0, sizeof(v));
	v.frame = 17;
	snprintf(v.newest, sizeof(v.newest), "flash1-20040112-234107");

	v.screen = SCREEN_HOME;
	v.check = CHECK_MATCHES;
	save(out, "home-matches", &v);
	v.check = CHECK_DIFFERS;
	v.check_differ = 2;
	save(out, "home-differs", &v);
	v.check = CHECK_NO_BACKUP;
	save(out, "home-no-backup", &v);

	v.screen = SCREEN_BACKUP;
	v.backup.phase = 0;
	save(out, "backup-1-about", &v);
	v.backup.phase = 1;
	v.backup.done = 3;
	snprintf(v.backup.what, sizeof(v.backup.what), "registry/system.dreg");
	save(out, "backup-2-copying", &v);
	v.backup.phase = 2;
	v.backup.result.done = 1;
	v.backup.result.files = 7;
	v.backup.result.bytes = 503146;
	v.backup.result.wallpaper = 1;
	snprintf(v.backup.result.folder, sizeof(v.backup.result.folder), "ms0:/BACKUP/flash1-20040112-234107");
	save(out, "backup-3-done", &v);

	v.screen = SCREEN_RESTORE_PICK;
	v.restore.count = 3;
	v.restore.selected = 0;
	snprintf(v.restore.names[0], RP2_BACKUP_NAME, "flash1-20040112-234418");
	snprintf(v.restore.names[1], RP2_BACKUP_NAME, "flash1-20040112-234401");
	snprintf(v.restore.names[2], RP2_BACKUP_NAME, "flash1-20040112-234107");
	save(out, "restore-1-pick", &v);

	memset(&plan, 0, sizeof(plan));
	snprintf(plan.folder, sizeof(plan.folder), "ms0:/BACKUP/flash1-20040112-234418");
	snprintf(plan.firmware, sizeof(plan.firmware), "6.61");
	plan.intact = 1;
	plan.same_firmware = 1;
	plan.count = 3;
	plan.differ = 2;
	snprintf(plan.files[0].path, sizeof(plan.files[0].path), "registry/system.dreg");
	plan.files[0].state = RP2_DIFFERS;
	snprintf(plan.files[1].path, sizeof(plan.files[1].path), "vsh/theme/wallpaper.bmp");
	plan.files[1].state = RP2_MISSING_NOW;
	snprintf(plan.files[2].path, sizeof(plan.files[2].path), "registry/system.ireg");
	v.screen = SCREEN_RESTORE_CHECK;
	v.restore.plan = &plan;
	v.restore.hold = 70;
	save(out, "restore-2-confirm", &v);
	plan.intact = 0;
	snprintf(plan.error, sizeof(plan.error), "a copy on the stick differs from its manifest");
	save(out, "restore-2-refused", &v);
	v.screen = SCREEN_RESTORE_WORK;
	save(out, "restore-3-writing", &v);
	v.screen = SCREEN_RESTORE_DONE;
	v.restore.result = 0;
	v.restore.countdown = 4;
	save(out, "restore-4-done", &v);

	v.screen = SCREEN_CONNECT;
	v.connect.wlan = 0;
	save(out, "connect-1-switch-off", &v);
	v.connect.wlan = 1;
	v.connect.net = 1;
	v.frame = 50;
	save(out, "connect-2-joining", &v);
	v.connect.net = 2;
	snprintf(v.connect.address, sizeof(v.connect.address), "10.0.0.40");
	v.connect.port = 56924;
	v.connect.served = 12;
	snprintf(v.connect.last, sizeof(v.connect.last), "stream");
	save(out, "connect-3-connected", &v);
	v.connect.net = -2;
	save(out, "connect-no-pairing", &v);

	/* the Wi-Fi check: a switch that reads off, then flickers; then a join */
	{
		int k;

		v.screen = SCREEN_WIFI;
		v.connect.wlan = 0;
		v.wifi.chip = 1;
		snprintf(v.wifi.vendor, sizeof(v.wifi.vendor), "00:1F:A7");
		v.wifi.saved = 1;
		snprintf(v.wifi.ssid, sizeof(v.wifi.ssid), "HomeNetwork");
		snprintf(v.wifi.security, sizeof(v.wifi.security), "WPA");
		v.wifi.samples = 80;
		save(out, "wifi-1-switch-off", &v);
		for (k = 0; k < WIFI_HISTORY; k++)
			v.wifi.history[k] = (unsigned char)(k > 60 && (k % 7 < 3));
		v.wifi.samples = WIFI_HISTORY;
		v.wifi.changes = 16;
		save(out, "wifi-2-flicker", &v);
		memset(v.wifi.history, 1, sizeof(v.wifi.history));
		v.wifi.changes = 1;
		v.connect.wlan = 1;
		v.wifi.test = -1;
		v.wifi.steps = 3;
		v.wifi.step[0].state = 1, v.wifi.step[0].ms = 300;
		v.wifi.step[1].state = 2, v.wifi.step[1].ms = 2100;
		v.wifi.step[2].state = 0, v.wifi.step[2].ms = 7400;
		v.wifi.error = (int)0x80410a0bu;
		save(out, "wifi-3-turned-away", &v);
		v.wifi.test = 2;
		v.wifi.error = 0;
		v.wifi.steps = 4;
		v.wifi.step[2].state = 3, v.wifi.step[2].ms = 3200;
		v.wifi.step[3].state = 4, v.wifi.step[3].ms = 4100;
		snprintf(v.wifi.ip, sizeof(v.wifi.ip), "10.0.0.40");
		v.wifi.strength = 78;
		v.wifi.channel = 6;
		snprintf(v.wifi.report, sizeof(v.wifi.report), "ms0:/halo/remotepilot-wifi.txt");
		save(out, "wifi-4-works", &v);
	}
	return 0;
}
