/* ui.h - the companion screen's drawing: anti-aliased shapes, baked fonts,
the PSP's face-button badges and a few icons, into a 32-bit 480x272 frame.

Portable C99 with no PSP calls: the PSP draws into its frame buffer
(platform_psp.c), and render_screens.c draws the same screens into images
on a PC so they can be looked at and tested without a console. Pixels are
the PSP's 8888 format: 0xAABBGGRR. */
#ifndef RP_UI_H
#define RP_UI_H

#include <stdint.h>

#define UI_W 480
#define UI_H 272
#define UI_RGB(r, g, b) (0xff000000u | (uint32_t)(b) << 16 | (uint32_t)(g) << 8 | (uint32_t)(r))

/* the palette: night blue with a cyan accent, as the XMB art */
#define UI_BG UI_RGB(8, 17, 31)
#define UI_DEEP UI_RGB(11, 42, 74)
#define UI_BLUE UI_RGB(21, 93, 158)
#define UI_PANEL UI_RGB(13, 30, 52)
#define UI_LINE UI_RGB(47, 95, 143)
#define UI_ACCENT UI_RGB(103, 220, 255)
#define UI_TEXT UI_RGB(241, 247, 255)
#define UI_MUTED UI_RGB(170, 192, 218)
#define UI_GOLD UI_RGB(255, 214, 120)
#define UI_GOOD UI_RGB(110, 231, 160)
#define UI_BAD UI_RGB(255, 128, 112)

struct ui_glyph
{
	unsigned short cp;
	signed char advance, x, y;
	unsigned char w, h;
	unsigned int offset;
};

struct ui_font
{
	int ascent, height, count;
	const struct ui_glyph *glyphs;
	const unsigned char *alpha;
};

extern const struct ui_font ui_font_title, ui_font_big, ui_font_head, ui_font_body, ui_font_label;

struct ui
{
	uint32_t *pixels;
	int stride;
};

enum ui_align { UI_LEFT, UI_CENTER, UI_RIGHT };
enum ui_icon { UI_ICON_SHIELD, UI_ICON_RESTORE, UI_ICON_WIFI, UI_ICON_CHECK, UI_ICON_WARN, UI_ICON_KEY, UI_ICON_SWITCH };

/* the backdrop (the XMB background's art), made once into UI_W * UI_H
pixels, then copied each frame */
void ui_background_make(uint32_t *out);
void ui_background(struct ui *ui, const uint32_t *background);
/* a light running along the backdrop's horizon, phase 0..1 */
void ui_horizon_glint(struct ui *ui, float phase);

void ui_fill(struct ui *ui, int x, int y, int w, int h, uint32_t color, int alpha);
void ui_round(struct ui *ui, float x, float y, float w, float h, float r, uint32_t color, int alpha);
void ui_round_line(struct ui *ui, float x, float y, float w, float h, float r, float thick, uint32_t color, int alpha);
void ui_circle(struct ui *ui, float cx, float cy, float r, uint32_t color, int alpha);
/* an arc from angle from to to (turns: 0 at the top, clockwise, 1 a full turn) */
void ui_ring(struct ui *ui, float cx, float cy, float r, float thick, float from, float to, uint32_t color, int alpha);
void ui_line(struct ui *ui, float x0, float y0, float x1, float y1, float thick, uint32_t color, int alpha);

/* text on a baseline at y; returns its width. UTF-8, the baked characters only */
int ui_text(struct ui *ui, const struct ui_font *font, int x, int y, const char *text, uint32_t color, int alpha,
            enum ui_align align);
int ui_text_width(const struct ui_font *font, const char *text);
/* wrapped to width, from the first baseline at y; returns the next line's baseline */
int ui_paragraph(struct ui *ui, const struct ui_font *font, int x, int y, int width, const char *text, uint32_t color,
                 int alpha);

/* a face button's badge: 't' triangle, 'c' circle, 'x' cross, 's' square */
void ui_button(struct ui *ui, float cx, float cy, float r, char which, int alpha);
void ui_icon(struct ui *ui, enum ui_icon icon, float cx, float cy, float size, uint32_t color, float phase);
/* a spinner of dots, turning with phase (0..1) */
void ui_spinner(struct ui *ui, float cx, float cy, float r, uint32_t color, float phase);
/* 0..1 of a bar, or (done < 0) a moving stripe for work of unknown length */
void ui_progress(struct ui *ui, int x, int y, int w, int h, float done, float phase);

#endif
