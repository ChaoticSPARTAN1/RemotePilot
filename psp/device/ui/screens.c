/* screens.c - RemotePilot PSP's guided screens (screens.h). */
#include "screens.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#define CARD_X 16
#define CARD_W 448

/* 0..1, once every 0.7 s: the "do this now" pulse */
static float pulse(const struct view *v)
{
	return 0.5f + 0.5f * sinf(v->frame * (2 * 3.14159265f / 42.0f));
}

static uint32_t mix(uint32_t a, uint32_t b, float t)
{
	int k;
	uint32_t out = 0xff000000u;

	for (k = 0; k < 24; k += 8)
	{
		float ca = (float)((a >> k) & 0xff), cb = (float)((b >> k) & 0xff);

		out |= (uint32_t)(ca + (cb - ca) * t) << k;
	}
	return out;
}

void screens_backup_date(const char *name, char *out, int size)
{
	const char *d = strncmp(name, "flash1-", 7) ? name : name + 7;

	if (strlen(d) >= 15 && d[8] == '-')
		snprintf(out, (size_t)size, "%.4s-%.2s-%.2s %.2s:%.2s:%.2s%s%s", d, d + 4, d + 6, d + 9, d + 11, d + 13,
			d[15] ? " #" : "", d[15] ? d + 16 : "");
	else
		snprintf(out, (size_t)size, "%s", name);
}

static void card(struct ui *ui, int y, int h)
{
	ui_round(ui, CARD_X, (float)y, CARD_W, (float)h, 12, UI_PANEL, 225);
	ui_round_line(ui, CARD_X + 0.5f, y + 0.5f, CARD_W - 1, (float)h - 1, 12, 1, UI_LINE, 255);
}

static void header(struct ui *ui, const char *section)
{
	ui_fill(ui, 0, 0, UI_W, 34, UI_BG, 150);
	ui_fill(ui, 0, 34, UI_W, 1, UI_LINE, 255);
	ui_circle(ui, 20, 17, 12, UI_DEEP, 255);
	ui_ring(ui, 20, 17, 12, 1.2f, 0, 1, UI_ACCENT, 255);
	ui_icon(ui, UI_ICON_WIFI, 20, 15, 16, UI_ACCENT, -1);
	ui_text(ui, &ui_font_title, 40, 25, "RemotePilot", UI_TEXT, 255, UI_LEFT);
	ui_text(ui, &ui_font_label, 40 + ui_text_width(&ui_font_title, "RemotePilot") + 6, 24, "PSP", UI_ACCENT, 255,
		UI_LEFT);
	ui_text(ui, &ui_font_label, UI_W - 14, 22, section, UI_MUTED, 255, UI_RIGHT);
}

/* the footer's hints: "x:Start c:Back" -> badges and words */
static void footer(struct ui *ui, const char *hints)
{
	char word[40];
	int x = 14;

	ui_fill(ui, 0, 248, UI_W, 24, UI_BG, 170);
	ui_fill(ui, 0, 248, UI_W, 1, UI_LINE, 255);
	while (*hints)
	{
		const char *end = strchr(hints, '|');
		int size = end ? (int)(end - hints) : (int)strlen(hints);

		snprintf(word, sizeof(word), "%.*s", size, hints);
		if (word[1] == ':' && strchr("tcxs", word[0]))
		{
			ui_button(ui, x + 8.0f, 260, 8, word[0], 255);
			x += 20;
			x += ui_text(ui, &ui_font_body, x, 264, word + 2, UI_TEXT, 255, UI_LEFT) + 16;
		}
		else
			x += ui_text(ui, &ui_font_body, x, 264, word, UI_MUTED, 255, UI_LEFT) + 16;
		hints += size + (end ? 1 : 0);
	}
}

/* step dots: done ones filled, the current one ringed, a stopped one red */
static void stepper(struct ui *ui, const char *const *labels, int count, int current, int stopped,
                    const struct view *v)
{
	int k, spacing = CARD_W / count;

	for (k = 0; k < count; k++)
	{
		float cx = CARD_X + spacing * (k + 0.5f), cy = 48;
		uint32_t color = k < current ? UI_ACCENT : k == current ? (stopped ? UI_BAD : UI_GOLD) : UI_LINE;

		if (k + 1 < count)
			ui_line(ui, cx + 9, cy, cx + spacing - 9, cy, 2, k < current ? UI_ACCENT : UI_LINE, 255);
		if (k < current)
			ui_icon(ui, UI_ICON_CHECK, cx, cy, 13, UI_ACCENT, 0);
		else
		{
			ui_circle(ui, cx, cy, 6.5f, UI_BG, 255);
			ui_ring(ui, cx, cy, 6, 2, 0, 1, color, 255);
			if (k == current && !stopped)
				ui_ring(ui, cx, cy, 9.5f, 1.2f, 0, 1, UI_GOLD, (int)(200 * pulse(v)));
		}
		ui_text(ui, &ui_font_label, (int)cx, 68, labels[k], k <= current ? UI_TEXT : UI_MUTED, 255, UI_CENTER);
	}
}

/* the one thing to do now: "PRESS [x] TO START", pulsing */
static void cue(struct ui *ui, int x, int y, int w, const char *before, char button, const char *after,
                const struct view *v, float hold)
{
	int width = ui_text_width(&ui_font_head, before) + 28 + ui_text_width(&ui_font_head, after);
	int left = x + (w - width) / 2;
	uint32_t edge = mix(UI_TEXT, UI_GOLD, pulse(v));

	ui_round(ui, (float)x, (float)y, (float)w, 34, 9, UI_GOLD, 26);
	ui_round_line(ui, x + 0.5f, y + 0.5f, (float)w - 1, 33, 9, 1.6f, edge, 255);
	left += ui_text(ui, &ui_font_head, left, y + 22, before, UI_TEXT, 255, UI_LEFT);
	ui_button(ui, left + 14.0f, y + 17.0f, 10, button, 255);
	if (hold > 0)
		ui_ring(ui, left + 14.0f, y + 17.0f, 13, 2.4f, 0, hold, UI_GOLD, 255);
	ui_text(ui, &ui_font_head, left + 28, y + 22, after, UI_TEXT, 255, UI_LEFT);
}

static void title_block(struct ui *ui, int x, int y, int w, const char *title, const char *body, uint32_t color)
{
	ui_text(ui, &ui_font_head, x, y, title, color, 255, UI_LEFT);
	if (body)
		ui_paragraph(ui, &ui_font_body, x, y + 20, w, body, UI_MUTED, 255);
}

/* ----- home */

static void tile(struct ui *ui, int x, char button, enum ui_icon icon, const char *title, const char *line1,
                 const char *line2, int attention, const struct view *v)
{
	int y = 120, w = 144, h = 112;
	float cx = x + w * 0.5f;

	ui_round(ui, (float)x, (float)y, (float)w, (float)h, 14, UI_PANEL, 225);
	ui_round_line(ui, x + 0.5f, y + 0.5f, (float)w - 1, (float)h - 1, 14, attention ? 2.0f : 1.0f,
		attention ? mix(UI_LINE, UI_GOLD, pulse(v)) : UI_LINE, 255);
	ui_circle(ui, cx, y + 28.0f, 20, UI_DEEP, 255);
	ui_ring(ui, cx, y + 28.0f, 20, 1.2f, 0, 1, attention ? UI_GOLD : UI_LINE, 255);
	ui_icon(ui, icon, cx, y + 28.0f, 24, attention ? UI_GOLD : UI_ACCENT, -1);
	ui_text(ui, &ui_font_head, (int)cx, y + 66, title, UI_TEXT, 255, UI_CENTER);
	ui_text(ui, &ui_font_body, (int)cx, y + 82, line1, UI_MUTED, 255, UI_CENTER);
	ui_text(ui, &ui_font_body, (int)cx, y + 96, line2, UI_MUTED, 255, UI_CENTER);
	ui_button(ui, cx, y + h - 1.0f, 10, button, 255);
}

/* RemotePilot's emblem as on its XMB art: Wi-Fi arcs over a dot, with a
wave running out through them */
static void emblem(struct ui *ui, float cx, float cy, float r, const struct view *v)
{
	float phase = (v->frame % 120) / 120.0f;
	int k;

	ui_circle(ui, cx, cy, r * 0.09f, UI_TEXT, 255);
	for (k = 0; k < 3; k++)
	{
		float wave = sinf((phase * 2 - k * 0.28f) * 2 * 3.14159265f);
		int alpha = 150 + (int)(105 * (wave > 0 ? wave : 0));

		ui_ring(ui, cx, cy, r * (0.35f + 0.325f * k), r * 0.07f, 0.875f, 1.125f, k < 2 ? UI_ACCENT : UI_TEXT, alpha);
	}
	/* the ripple past the last arc */
	ui_ring(ui, cx, cy, r * (1.05f + phase * 0.45f), r * 0.04f, 0.88f, 1.12f, UI_ACCENT, (int)(150 * (1 - phase)));
}

static void home(struct ui *ui, const struct view *v)
{
	char date[48], line[96];
	float phase = (v->frame % 60) / 60.0f;

	/* the hero: the XMB background's look, alive */
	ui_horizon_glint(ui, (v->frame % 600) / 600.0f);
	emblem(ui, 422, 56, 46, v);
	ui_text(ui, &ui_font_title, 20, 36, "RemotePilot", UI_TEXT, 255, UI_LEFT);
	ui_text(ui, &ui_font_title, 24 + ui_text_width(&ui_font_title, "RemotePilot"), 36, "PSP", UI_ACCENT, 255, UI_LEFT);
	ui_text(ui, &ui_font_label, 21, 54, "BACKUP  ·  RESTORE  ·  REMOTE LINK", UI_ACCENT, 220, UI_LEFT);
	card(ui, 66, 46);
	screens_backup_date(v->newest, date, sizeof(date));
	switch (v->check)
	{
	case CHECK_RUNNING:
		ui_spinner(ui, 42, 89, 10, UI_ACCENT, phase);
		title_block(ui, 64, 85, 380, "Checking your settings…", NULL, UI_TEXT);
		ui_text(ui, &ui_font_body, 64, 103, "Comparing them with your newest backup.", UI_MUTED, 255, UI_LEFT);
		break;
	case CHECK_MATCHES:
		ui_icon(ui, UI_ICON_SHIELD, 42, 89, 30, UI_GOOD, 0);
		ui_text(ui, &ui_font_head, 64, 85, "Your settings match your backup", UI_GOOD, 255, UI_LEFT);
		snprintf(line, sizeof(line), "Newest backup: %s", date);
		ui_text(ui, &ui_font_body, 64, 103, line, UI_MUTED, 255, UI_LEFT);
		break;
	case CHECK_DIFFERS:
		ui_icon(ui, UI_ICON_WARN, 42, 89, 22, UI_GOLD, 0);
		ui_text(ui, &ui_font_head, 64, 85, "Your settings changed since your backup", UI_GOLD, 255, UI_LEFT);
		snprintf(line, sizeof(line), "%d file%s differ from %s. Press □ to look.", v->check_differ,
			v->check_differ == 1 ? "" : "s", date);
		ui_text(ui, &ui_font_body, 64, 103, line, UI_MUTED, 255, UI_LEFT);
		break;
	case CHECK_NO_BACKUP:
		ui_icon(ui, UI_ICON_WARN, 42, 89, 22, UI_ACCENT, 0);
		ui_text(ui, &ui_font_head, 64, 85, "No backup on this Memory Stick yet", UI_ACCENT, 255, UI_LEFT);
		ui_text(ui, &ui_font_body, 64, 103, "Press △ to save your wallpaper, theme and settings first.", UI_MUTED, 255,
			UI_LEFT);
		break;
	default:
		ui_icon(ui, UI_ICON_WARN, 42, 89, 22, UI_BAD, 0);
		ui_text(ui, &ui_font_head, 64, 85, "Your settings can't be checked", UI_BAD, 255, UI_LEFT);
		ui_text(ui, &ui_font_body, 64, 103, "The newest backup couldn't be read. Make a new one with △.", UI_MUTED, 255,
			UI_LEFT);
		break;
	}
	tile(ui, 16, 't', UI_ICON_SHIELD, "Back up", "Save your settings", "to the Memory Stick",
		v->check == CHECK_NO_BACKUP || v->check == CHECK_UNREADABLE, v);
	tile(ui, 168, 's', UI_ICON_RESTORE, "Restore", "Put a backup back", "after a reset", v->check == CHECK_DIFFERS, v);
	tile(ui, 320, 'x', UI_ICON_WIFI, "Connect", "Link with the", "PC page over Wi-Fi", 0, v);
	footer(ui, "t:Back up|s:Restore|x:Connect|HOME  quit");
}

/* ----- backup */

static void backup(struct ui *ui, const struct view *v)
{
	static const char *const steps[] = { "Read settings", "Copy to card", "Check copies" };
	const struct rp2_backup_result *r = &v->backup.result;
	char line[128];

	header(ui, "SETTINGS BACKUP");
	stepper(ui, steps, 3, v->backup.phase == 0 ? 0 : v->backup.phase == 1 ? 1 : v->backup.phase == 2 ? 3 : 1,
		v->backup.phase == 3, v);
	card(ui, 80, 160);
	switch (v->backup.phase)
	{
	case 0:
		ui_circle(ui, 66, 140, 34, UI_DEEP, 255);
		ui_icon(ui, UI_ICON_SHIELD, 66, 140, 44, UI_ACCENT, 0);
		title_block(ui, 118, 104, 330, "Back up your PSP settings",
			"Your wallpaper, theme, Wi-Fi connections and system settings go into a new folder in ms0:/BACKUP, "
			"and every copy is checked. Your settings are only read.", UI_TEXT);
		cue(ui, 118, 194, 330, "PRESS", 'x', "TO START", v, 0);
		footer(ui, "x:Start|c:Back");
		break;
	case 1:
		ui_spinner(ui, 66, 140, 20, UI_ACCENT, (v->frame % 60) / 60.0f);
		snprintf(line, sizeof(line), "%d file%s copied. Keep the PSP on.", v->backup.done, v->backup.done == 1 ? "" : "s");
		title_block(ui, 118, 110, 330, "Backing up…", line, UI_TEXT);
		ui_text(ui, &ui_font_label, 118, 166, v->backup.what, UI_ACCENT, 255, UI_LEFT);
		ui_progress(ui, 118, 182, 328, 8, -1, (v->frame % 90) / 90.0f);
		footer(ui, "Working… a few seconds");
		break;
	case 2:
		ui_icon(ui, UI_ICON_CHECK, 66, 140, 52, UI_GOOD, 0);
		ui_text(ui, &ui_font_head, 118, 108, "Backed up and checked", UI_GOOD, 255, UI_LEFT);
		snprintf(line, sizeof(line), "%d files · %lu KB · each copy read back the same", r->files,
			(r->bytes + 1023) / 1024);
		ui_text(ui, &ui_font_body, 118, 130, line, UI_TEXT, 255, UI_LEFT);
		snprintf(line, sizeof(line), "Wallpaper: %s     Custom theme: %s", r->wallpaper ? "✓ included" : "none set",
			r->theme ? "✓ included" : "none installed");
		ui_text(ui, &ui_font_body, 118, 148, line, UI_TEXT, 255, UI_LEFT);
		ui_text(ui, &ui_font_label, 118, 168, r->folder, UI_ACCENT, 255, UI_LEFT);
		if (r->failed)
		{
			snprintf(line, sizeof(line), "%d file%s couldn't be copied.", r->failed, r->failed == 1 ? "" : "s");
			ui_text(ui, &ui_font_body, 118, 186, line, UI_GOLD, 255, UI_LEFT);
		}
		ui_paragraph(ui, &ui_font_body, 118, 210, 330,
			"Next: keep a copy on your PC too, with a card reader or Connect.", UI_MUTED, 255);
		footer(ui, "c:Home");
		break;
	default:
		ui_icon(ui, UI_ICON_WARN, 66, 140, 44, UI_BAD, 0);
		title_block(ui, 118, 110, 330, "Backup stopped", r->error[0] ? r->error : "Something went wrong.", UI_BAD);
		ui_paragraph(ui, &ui_font_body, 118, 170, 330, "Nothing on your PSP was changed. You can try again.", UI_MUTED,
			255);
		footer(ui, "c:Home");
		break;
	}
}

/* ----- restore */

static const char *const restore_steps[] = { "Pick", "Check", "Confirm", "Restore", "Restart" };

static void restore_pick(struct ui *ui, const struct view *v)
{
	char date[48];
	int k, first = v->restore.selected > 4 ? v->restore.selected - 4 : 0;

	header(ui, "SETTINGS RESTORE");
	stepper(ui, restore_steps, 5, 0, 0, v);
	card(ui, 80, 160);
	ui_text(ui, &ui_font_head, 34, 102, "Pick a backup to put back", UI_TEXT, 255, UI_LEFT);
	if (!v->restore.count)
	{
		ui_paragraph(ui, &ui_font_body, 34, 128, 410,
			"There's no backup on this Memory Stick yet. Go back with ○ and press △ on the home screen to make one.",
			UI_MUTED, 255);
		footer(ui, "c:Back");
		return;
	}
	for (k = first; k < v->restore.count && k < first + 5; k++)
	{
		int y = 114 + (k - first) * 24;

		screens_backup_date(v->restore.names[k], date, sizeof(date));
		if (k == v->restore.selected)
		{
			ui_round(ui, 28, (float)y, 424, 22, 6, UI_ACCENT, 40);
			ui_round_line(ui, 28.5f, y + 0.5f, 423, 21, 6, 1.4f, mix(UI_ACCENT, UI_GOLD, pulse(v)), 255);
		}
		ui_icon(ui, UI_ICON_SHIELD, 44, y + 11.0f, 15, k == v->restore.selected ? UI_GOLD : UI_ACCENT, 0);
		ui_text(ui, &ui_font_body, 60, y + 16, date, UI_TEXT, 255, UI_LEFT);
		if (k == 0)
			ui_text(ui, &ui_font_label, 440, y + 15, "NEWEST", UI_GOOD, 255, UI_RIGHT);
	}
	footer(ui, "↑↓ choose|x:Check it|c:Back");
}

static void restore_check(struct ui *ui, const struct view *v)
{
	const struct rp2_restore_plan *p = v->restore.plan;
	char line[160], date[48];
	int k, shown = 0, ok = p && !p->error[0];

	header(ui, "SETTINGS RESTORE");
	stepper(ui, restore_steps, 5, ok && p->differ ? 2 : 1, !ok, v);
	card(ui, 80, 160);
	if (!p)
		return;
	screens_backup_date(p->folder + (strncmp(p->folder, "ms0:/BACKUP/", 12) ? 0 : 12), date, sizeof(date));
	snprintf(line, sizeof(line), "Backup from %s", date);
	ui_text(ui, &ui_font_head, 34, 102, line, UI_TEXT, 255, UI_LEFT);
	/* the checks */
	ui_icon(ui, p->intact ? UI_ICON_CHECK : UI_ICON_WARN, 42, 120, 13, p->intact ? UI_GOOD : UI_BAD, 0);
	ui_text(ui, &ui_font_body, 56, 124, p->intact ? "Copies on the card are intact" : "A copy on the card is damaged",
		UI_TEXT, 255, UI_LEFT);
	if (p->same_firmware == 1)
		snprintf(line, sizeof(line), "Made on this firmware (%s)", p->firmware);
	else if (p->same_firmware == -1)
		snprintf(line, sizeof(line), "Firmware not recorded (an older backup)");
	else
		snprintf(line, sizeof(line), "Made on firmware %s: not this PSP's", p->firmware);
	ui_icon(ui, p->same_firmware ? UI_ICON_CHECK : UI_ICON_WARN, 42, 140, 13,
		p->same_firmware == 1 ? UI_GOOD : p->same_firmware == -1 ? UI_GOLD : UI_BAD, 0);
	ui_text(ui, &ui_font_body, 56, 144, line, UI_TEXT, 255, UI_LEFT);
	if (p->differ)
		snprintf(line, sizeof(line), "%d file%s will be put back:", p->differ, p->differ == 1 ? "" : "s");
	else
		snprintf(line, sizeof(line), "Your settings already match this backup");
	ui_icon(ui, p->differ ? UI_ICON_RESTORE : UI_ICON_CHECK, 42, 160, 13, p->differ ? UI_GOLD : UI_GOOD, 0);
	ui_text(ui, &ui_font_body, 56, 164, line, UI_TEXT, 255, UI_LEFT);
	/* what changes, beside the checks */
	for (k = 0; k < p->count && shown < 4; k++)
		if (p->files[k].state != RP2_SAME)
		{
			snprintf(line, sizeof(line), "%s %s", p->files[k].state == RP2_MISSING_NOW ? "+" : "~", p->files[k].path);
			ui_text(ui, &ui_font_label, 290, 124 + shown * 14, line, UI_GOLD, 255, UI_LEFT);
			shown++;
		}
	if (!ok)
	{
		ui_paragraph(ui, &ui_font_body, 34, 194, 410, p->error, UI_BAD, 255);
		ui_text(ui, &ui_font_body, 34, 226, "Nothing was changed.", UI_MUTED, 255, UI_LEFT);
		footer(ui, "c:Back");
	}
	else if (!p->differ)
	{
		ui_text(ui, &ui_font_body, 34, 200, "Nothing to restore. Your PSP is as this backup left it.", UI_GOOD, 255,
			UI_LEFT);
		footer(ui, "c:Back");
	}
	else
	{
		cue(ui, 34, 186, 410, "HOLD", 'x', "FOR 2 SECONDS TO RESTORE", v,
			v->restore.hold / (float)RESTORE_HOLD_FRAMES);
		ui_text(ui, &ui_font_label, 240, 234, "Then the PSP restarts by itself to load them.", UI_MUTED, 255, UI_CENTER);
		footer(ui, "x:hold to restore|c:Back");
	}
}

static void restore_work(struct ui *ui, const struct view *v)
{
	header(ui, "SETTINGS RESTORE");
	stepper(ui, restore_steps, 5, 3, 0, v);
	card(ui, 80, 160);
	ui_spinner(ui, 66, 140, 20, UI_GOLD, (v->frame % 60) / 60.0f);
	title_block(ui, 118, 112, 330, "Putting your settings back…",
		"Each file is written and read back. Don't turn the PSP off.", UI_TEXT);
	ui_progress(ui, 118, 180, 328, 8, -1, (v->frame % 90) / 90.0f);
	footer(ui, "Working… don't turn the PSP off");
}

static void restore_done(struct ui *ui, const struct view *v)
{
	char line[96];

	header(ui, "SETTINGS RESTORE");
	stepper(ui, restore_steps, 5, v->restore.result ? 3 : 4, v->restore.result != 0, v);
	card(ui, 80, 160);
	if (!v->restore.result)
	{
		ui_icon(ui, UI_ICON_CHECK, 66, 140, 52, UI_GOOD, 0);
		ui_text(ui, &ui_font_head, 118, 112, "Restored and checked", UI_GOOD, 255, UI_LEFT);
		ui_paragraph(ui, &ui_font_body, 118, 132, 330,
			"Every file matches your backup again. The PSP restarts now so it loads them, before anything can "
			"write over them.", UI_MUTED, 255);
		snprintf(line, sizeof(line), "Restarting in %d…", v->restore.countdown);
		ui_text(ui, &ui_font_big, 118, 216, line, UI_TEXT, 255, UI_LEFT);
		footer(ui, "x:Restart now");
	}
	else
	{
		ui_icon(ui, UI_ICON_WARN, 66, 140, 44, UI_BAD, 0);
		title_block(ui, 118, 112, 330, "Restore stopped",
			v->restore.result == -2 ?
			"Your settings as they are now couldn't all be backed up first, so nothing was written. Make room on "
			"the Memory Stick and try again." :
			"A file couldn't be written or didn't read back the same. Your settings from just before are in a new "
			"backup, and the one you chose is still there: you can try again. If the PSP asks to reset its "
			"settings at the next start, let it, then restore again.",
			UI_BAD);
		footer(ui, "c:Home");
	}
}

/* ----- connect */

static void connect(struct ui *ui, const struct view *v)
{
	static const char *const steps[] = { "WLAN switch", "Join Wi-Fi", "Pairing", "Connected" };
	const char *title, *body;
	char line[96], named[64];
	int step, stopped = 0;
	float phase = (v->frame % 80) / 80.0f;

	header(ui, "CONNECT TO PC");
	if (v->connect.net == -2)
		step = 2, stopped = 1;
	else if (v->connect.wlan == 0)
		step = 0, stopped = 1;
	else if (v->connect.net == 2)
		step = 4;
	else
		step = 1, stopped = v->connect.net == -1;
	stepper(ui, steps, 4, step > 3 ? 4 : step, stopped, v);
	card(ui, 80, 160);
	ui_circle(ui, 66, 140, 34, UI_DEEP, 255);
	if (v->connect.net == -2)
	{
		ui_icon(ui, UI_ICON_KEY, 66, 140, 40, UI_GOLD, 0);
		title = "No pairing file yet";
		body = "On the PC page choose your PSP preset, then Prepare pairing and copy the file to the Memory Stick. "
			"It writes remotepilot/remotepilot.cfg. Then come back here.";
	}
	else if (v->connect.wlan == 0)
	{
		ui_icon(ui, UI_ICON_SWITCH, 66, 140, 44, UI_GOLD, 0);
		title = "Turn on the WLAN switch";
		body = "It's on the left edge of the PSP: slide it up. This screen notices by itself. If it's already up and "
			"this stays, press △ for a Wi-Fi check.";
	}
	else if (v->connect.net == 2)
	{
		ui_icon(ui, UI_ICON_WIFI, 66, 146, 50, UI_GOOD, -1);
		ui_text(ui, &ui_font_head, 118, 104, "Connected", UI_GOOD, 255, UI_LEFT);
		ui_text(ui, &ui_font_big, 118, 136, v->connect.address, UI_TEXT, 255, UI_LEFT);
		snprintf(line, sizeof(line), "port %u", v->connect.port);
		ui_text(ui, &ui_font_label, 118 + ui_text_width(&ui_font_big, v->connect.address) + 10, 134, line, UI_ACCENT, 255,
			UI_LEFT);
		ui_paragraph(ui, &ui_font_body, 118, 158, 330,
			"The PC page finds the PSP by itself. Its buttons and nub drive these screens; a restore still needs "
			"this PSP's own ✕.", UI_MUTED, 255);
		snprintf(line, sizeof(line), "Requests %u · refused %u · last: %s", v->connect.served, v->connect.refused,
			v->connect.last);
		ui_text(ui, &ui_font_label, 118, 214, line, UI_ACCENT, 255, UI_LEFT);
		footer(ui, "c:Back (stays connected)");
		return;
	}
	else if (v->connect.net == -1)
	{
		ui_icon(ui, UI_ICON_WARN, 66, 140, 40, UI_BAD, 0);
		snprintf(named, sizeof(named), "Couldn't join %s", v->wifi.ssid[0] ? v->wifi.ssid : "your Wi-Fi");
		ui_text(ui, &ui_font_head, 118, 104, named, UI_BAD, 255, UI_LEFT);
		ui_paragraph(ui, &ui_font_body, 118, 124, 330,
			"RemotePilot uses the first network in Settings > Network Settings > Infrastructure Mode. Press △ "
			"for a Wi-Fi check: it shows where joining stops.", UI_MUTED, 255);
		cue(ui, 118, 194, 330, "PRESS", 'x', "TO TRY AGAIN", v, 0);
		footer(ui, "x:Try again|t:Wi-Fi check|c:Back");
		return;
	}
	else
	{
		ui_icon(ui, UI_ICON_WIFI, 66, 146, 50, UI_ACCENT, phase);
		snprintf(named, sizeof(named), "Joining %s…", v->wifi.ssid[0] ? v->wifi.ssid : "your Wi-Fi");
		title = named;
		body = "The first network in Settings > Network Settings > Infrastructure Mode. This takes up to 30 seconds.";
	}
	ui_text(ui, &ui_font_head, 118, 104, title, UI_TEXT, 255, UI_LEFT);
	ui_paragraph(ui, &ui_font_body, 118, 124, 330, body, UI_MUTED, 255);
	footer(ui, "t:Wi-Fi check|c:Back");
}

/* ----- the Wi-Fi check */

const char *screens_apctl_state(int state)
{
	static const char *const names[] = { "disconnected", "scanning", "joining", "getting an address", "got an address",
		"signing in (EAP)", "exchanging keys" };

	return state >= 0 && state <= 6 ? names[state] : "?";
}

void screens_wifi_verdict(const struct view *v, char *out, int size)
{
	int reached = 0, k;

	for (k = 0; k < v->wifi.steps; k++)
		if (v->wifi.step[k].state > reached && v->wifi.step[k].state <= 4)
			reached = v->wifi.step[k].state;
	if (v->wifi.changes >= 6 && v->wifi.samples < WIFI_HISTORY * 3)
		snprintf(out, (size_t)size, "The switch reading flickers: its contacts are worn or dirty. Cleaning the switch "
			"usually fixes this.");
	else if (v->connect.wlan == 0 && v->wifi.chip == 1)
		snprintf(out, (size_t)size, "The Wi-Fi chip answers, but the switch reads OFF. The switch's contacts are the "
			"likely fault, not the Wi-Fi itself.");
	else if (v->connect.wlan == 0)
		snprintf(out, (size_t)size, "The switch reads OFF, so the firmware keeps Wi-Fi off. Slide it up; if the reading "
			"never changes, the switch needs cleaning.");
	else if (v->wifi.chip == 0)
		snprintf(out, (size_t)size, "The Wi-Fi chip doesn't answer: this looks like a hardware fault inside the PSP.");
	else if (!v->wifi.saved)
		snprintf(out, (size_t)size, "No network is saved yet. Add yours in Settings > Network Settings > "
			"Infrastructure Mode.");
	else if (v->wifi.test == 2)
		snprintf(out, (size_t)size, "Wi-Fi works: the PSP joined and got an address (signal %d%%).", v->wifi.strength);
	else if (v->wifi.test == 1)
		snprintf(out, (size_t)size, "Joining… each step is listed as it happens.");
	else if (v->wifi.test == -1 && reached >= 3)
		snprintf(out, (size_t)size, "The router let the PSP in but gave it no address: check the router's DHCP, or set "
			"a manual IP for that network in Network Settings.");
	else if (v->wifi.test == -1 && reached >= 2)
		snprintf(out, (size_t)size, "The router turned the PSP away while joining: check the password and security "
			"type, and that the router still allows older (802.11b, WPA) devices.");
	else if (v->wifi.test == -1)
		snprintf(out, (size_t)size, "The PSP didn't find your network: it may be 5 GHz only, hidden, or out of range. "
			"The PSP needs 2.4 GHz.");
	else
		snprintf(out, (size_t)size, "Press ✕ to try joining %s and watch each step.",
			v->wifi.ssid[0] ? v->wifi.ssid : "your network");
}

static void wifi_row(struct ui *ui, int y, int state, const char *name, const char *value)
{
	ui_icon(ui, state > 0 ? UI_ICON_CHECK : UI_ICON_WARN, 34, y - 4.0f, 12,
		state > 0 ? UI_GOOD : state == 0 ? UI_BAD : UI_MUTED, 0);
	ui_text(ui, &ui_font_label, 46, y, name, UI_MUTED, 255, UI_LEFT);
	ui_text(ui, &ui_font_body, 140, y + 1, value, UI_TEXT, 255, UI_LEFT);
}

static void wifi(struct ui *ui, const struct view *v)
{
	char line[160], verdict[200];
	int k, x;

	header(ui, "WI-FI CHECK");
	card(ui, 42, 202);
	/* the switch, live, with its last twelve seconds as a strip */
	wifi_row(ui, 62, v->connect.wlan == 1, "WLAN SWITCH", v->connect.wlan == 1 ? "ON" : v->connect.wlan == 0 ? "OFF" : "?");
	for (k = 0; k < WIFI_HISTORY; k++)
	{
		int on = v->wifi.history[k];

		ui_fill(ui, 196 + k * 3 / 2, on ? 51 : 58, 2, on ? 9 : 5, on ? UI_GOOD : UI_BAD,
			k < WIFI_HISTORY - v->wifi.samples ? 50 : 255);
	}
	snprintf(line, sizeof(line), "%d change%s", v->wifi.changes, v->wifi.changes == 1 ? "" : "s");
	ui_text(ui, &ui_font_label, 446, 62, line, v->wifi.changes >= 6 ? UI_GOLD : UI_MUTED, 255, UI_RIGHT);
	if (v->wifi.chip == 1)
		snprintf(line, sizeof(line), "answers (address %s:…)%s", v->wifi.vendor, v->wifi.power ? ", powered" : "");
	else
		snprintf(line, sizeof(line), v->wifi.chip == 0 ? "no answer" : "not asked yet");
	wifi_row(ui, 82, v->wifi.chip, "WI-FI CHIP", line);
	if (v->wifi.saved)
		snprintf(line, sizeof(line), "%s (%s, saved as #%d)", v->wifi.ssid, v->wifi.security, v->wifi.index);
	wifi_row(ui, 102, v->wifi.saved ? 1 : 0, "NETWORK", v->wifi.saved ? line : "none saved");
	/* the join, step by step */
	if (!v->wifi.steps)
		snprintf(line, sizeof(line), v->wifi.test == 1 ? "starting…" : "not tried yet");
	else
	{
		line[0] = 0;
		for (k = v->wifi.steps > 3 ? v->wifi.steps - 3 : 0; k < v->wifi.steps; k++)
		{
			size_t at = strlen(line);

			snprintf(line + at, sizeof(line) - at, "%s%s %.1fs", at ? " → " : "", screens_apctl_state(v->wifi.step[k].state),
				v->wifi.step[k].ms / 1000.0f);
		}
	}
	wifi_row(ui, 122, v->wifi.test == 2 ? 1 : v->wifi.test == -1 ? 0 : -1, "JOIN TEST", line);
	if (v->wifi.test == 2)
		snprintf(line, sizeof(line), "%s · signal %d%% · channel %d", v->wifi.ip, v->wifi.strength, v->wifi.channel);
	else if (v->wifi.error)
		snprintf(line, sizeof(line), "firmware error %08X", (unsigned int)v->wifi.error);
	else
		snprintf(line, sizeof(line), "–");
	wifi_row(ui, 142, v->wifi.test == 2 ? 1 : v->wifi.error ? 0 : -1, "RESULT", line);
	if (v->wifi.test == 1)
		ui_spinner(ui, 446, 118, 7, UI_ACCENT, (v->frame % 60) / 60.0f);
	/* what it means */
	ui_fill(ui, 28, 156, 424, 1, UI_LINE, 255);
	screens_wifi_verdict(v, verdict, sizeof(verdict));
	x = ui_paragraph(ui, &ui_font_body, 34, 174, 412, verdict,
		v->wifi.test == 2 ? UI_GOOD : v->connect.wlan == 0 || v->wifi.test == -1 || !v->wifi.chip ? UI_GOLD : UI_TEXT,
		255);
	if (v->wifi.report[0])
	{
		snprintf(line, sizeof(line), "Report saved: %s", v->wifi.report);
		ui_text(ui, &ui_font_label, 34, x + 2, line, UI_ACCENT, 255, UI_LEFT);
	}
	footer(ui, "x:Join test|t:Save report|c:Back");
}

void screens_draw(struct ui *ui, const uint32_t *background, const struct view *view)
{
	ui_background(ui, background);
	switch (view->screen)
	{
	case SCREEN_HOME: home(ui, view); break;
	case SCREEN_BACKUP: backup(ui, view); break;
	case SCREEN_RESTORE_PICK: restore_pick(ui, view); break;
	case SCREEN_RESTORE_CHECK: restore_check(ui, view); break;
	case SCREEN_RESTORE_WORK: restore_work(ui, view); break;
	case SCREEN_RESTORE_DONE: restore_done(ui, view); break;
	case SCREEN_CONNECT: connect(ui, view); break;
	case SCREEN_WIFI: wifi(ui, view); break;
	}
}
