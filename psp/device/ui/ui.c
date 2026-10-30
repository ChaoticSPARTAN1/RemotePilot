/* ui.c - the companion screen's drawing (ui.h). Shapes are drawn by their
distance to each pixel, so edges are smooth at any size. */
#include "ui.h"

#include <math.h>
#include <string.h>

#define PI 3.14159265f

static float clampf(float v, float low, float high)
{
	return v < low ? low : v > high ? high : v;
}

static void blend(struct ui *ui, int x, int y, uint32_t color, int alpha)
{
	uint32_t *p, d;
	unsigned int a;

	if (x < 0 || y < 0 || x >= UI_W || y >= UI_H || alpha <= 0)
		return;
	p = ui->pixels + y * ui->stride + x;
	if (alpha >= 255)
	{
		*p = color | 0xff000000u;
		return;
	}
	a = (unsigned int)alpha;
	d = *p;
	*p = 0xff000000u | ((((color & 0xff) * a + (d & 0xff) * (255 - a)) / 255) & 0xff) |
		(((((color >> 8) & 0xff) * a + ((d >> 8) & 0xff) * (255 - a)) / 255) << 8) |
		(((((color >> 16) & 0xff) * a + ((d >> 16) & 0xff) * (255 - a)) / 255) << 16);
}

/* coverage of a pixel whose centre is d pixels outside a shape's edge */
static int cover(float d, int alpha)
{
	return (int)(clampf(0.5f - d, 0.0f, 1.0f) * (float)alpha);
}

void ui_fill(struct ui *ui, int x, int y, int w, int h, uint32_t color, int alpha)
{
	int i, j;

	for (j = y; j < y + h; j++)
		for (i = x; i < x + w; i++)
			blend(ui, i, j, color, alpha);
}

static float round_distance(float px, float py, float x, float y, float w, float h, float r)
{
	float cx = x + w * 0.5f, cy = y + h * 0.5f;
	float qx = fabsf(px - cx) - (w * 0.5f - r), qy = fabsf(py - cy) - (h * 0.5f - r);
	float ox = qx > 0 ? qx : 0, oy = qy > 0 ? qy : 0;

	return sqrtf(ox * ox + oy * oy) + (qx > qy ? (qx < 0 ? qx : 0) : (qy < 0 ? qy : 0)) - r;
}

void ui_round(struct ui *ui, float x, float y, float w, float h, float r, uint32_t color, int alpha)
{
	int i, j;

	for (j = (int)y - 1; j <= (int)(y + h) + 1; j++)
		for (i = (int)x - 1; i <= (int)(x + w) + 1; i++)
			blend(ui, i, j, color, cover(round_distance(i + 0.5f, j + 0.5f, x, y, w, h, r), alpha));
}

void ui_round_line(struct ui *ui, float x, float y, float w, float h, float r, float thick, uint32_t color, int alpha)
{
	int i, j;

	for (j = (int)(y - thick) - 1; j <= (int)(y + h + thick) + 1; j++)
		for (i = (int)(x - thick) - 1; i <= (int)(x + w + thick) + 1; i++)
			blend(ui, i, j, color,
				cover(fabsf(round_distance(i + 0.5f, j + 0.5f, x, y, w, h, r)) - thick * 0.5f, alpha));
}

void ui_circle(struct ui *ui, float cx, float cy, float r, uint32_t color, int alpha)
{
	int i, j;

	for (j = (int)(cy - r) - 1; j <= (int)(cy + r) + 1; j++)
		for (i = (int)(cx - r) - 1; i <= (int)(cx + r) + 1; i++)
		{
			float dx = i + 0.5f - cx, dy = j + 0.5f - cy;

			blend(ui, i, j, color, cover(sqrtf(dx * dx + dy * dy) - r, alpha));
		}
}

void ui_ring(struct ui *ui, float cx, float cy, float r, float thick, float from, float to, uint32_t color, int alpha)
{
	float outer = r + thick;
	int i, j;

	for (j = (int)(cy - outer) - 1; j <= (int)(cy + outer) + 1; j++)
		for (i = (int)(cx - outer) - 1; i <= (int)(cx + outer) + 1; i++)
		{
			float dx = i + 0.5f - cx, dy = j + 0.5f - cy, turn = atan2f(dx, -dy) / (2 * PI);
			float d = fabsf(sqrtf(dx * dx + dy * dy) - r) - thick * 0.5f;

			if (turn < 0)
				turn += 1;
			/* the arc's ends, softened over about a pixel */
			if (to - from < 1)
			{
				float at = turn - from;

				if (at < 0)
					at += 1;
				if (at > to - from)
				{
					float past = (at - (to - from)) * 2 * PI * r, before = (1 - at) * 2 * PI * r;
					float edge = past < before ? past : before;

					d = d > edge ? d : edge;
				}
			}
			blend(ui, i, j, color, cover(d, alpha));
		}
}

void ui_line(struct ui *ui, float x0, float y0, float x1, float y1, float thick, uint32_t color, int alpha)
{
	float low_x = (x0 < x1 ? x0 : x1) - thick, high_x = (x0 > x1 ? x0 : x1) + thick;
	float low_y = (y0 < y1 ? y0 : y1) - thick, high_y = (y0 > y1 ? y0 : y1) + thick;
	float vx = x1 - x0, vy = y1 - y0, length = vx * vx + vy * vy;
	int i, j;

	for (j = (int)low_y - 1; j <= (int)high_y + 1; j++)
		for (i = (int)low_x - 1; i <= (int)high_x + 1; i++)
		{
			float px = i + 0.5f - x0, py = j + 0.5f - y0;
			float t = length > 0 ? clampf((px * vx + py * vy) / length, 0, 1) : 0;
			float dx = px - vx * t, dy = py - vy * t;

			blend(ui, i, j, color, cover(sqrtf(dx * dx + dy * dy) - thick * 0.5f, alpha));
		}
}

/* ----- text */

static const char *next_point(const char *text, unsigned int *cp)
{
	const unsigned char *s = (const unsigned char *)text;

	if (s[0] < 0x80)
		*cp = s[0];
	else if ((s[0] & 0xe0) == 0xc0 && s[1])
	{
		*cp = (unsigned int)(s[0] & 0x1f) << 6 | (s[1] & 0x3f);
		return text + 2;
	}
	else if ((s[0] & 0xf0) == 0xe0 && s[1] && s[2])
	{
		*cp = (unsigned int)(s[0] & 0x0f) << 12 | (unsigned int)(s[1] & 0x3f) << 6 | (s[2] & 0x3f);
		return text + 3;
	}
	else
		*cp = '?';
	return text + 1;
}

static const struct ui_glyph *glyph(const struct ui_font *font, unsigned int cp)
{
	int k;

	if (cp >= 32 && cp < 127)
		return &font->glyphs[cp - 32];
	for (k = 95; k < font->count; k++)
		if (font->glyphs[k].cp == cp)
			return &font->glyphs[k];
	return &font->glyphs['?' - 32];
}

int ui_text_width(const struct ui_font *font, const char *text)
{
	unsigned int cp;
	int width = 0;

	while (*text)
	{
		text = next_point(text, &cp);
		width += glyph(font, cp)->advance;
	}
	return width;
}

int ui_text(struct ui *ui, const struct ui_font *font, int x, int y, const char *text, uint32_t color, int alpha,
            enum ui_align align)
{
	int width = ui_text_width(font, text), pen;
	unsigned int cp;

	pen = align == UI_CENTER ? x - width / 2 : align == UI_RIGHT ? x - width : x;
	while (*text)
	{
		const struct ui_glyph *g;
		int i, j;

		text = next_point(text, &cp);
		g = glyph(font, cp);
		for (j = 0; j < g->h; j++)
			for (i = 0; i < g->w; i++)
			{
				int a = font->alpha[g->offset + j * g->w + i];

				if (a)
					blend(ui, pen + g->x + i, y + g->y + j, color, a * alpha / 255);
			}
		pen += g->advance;
	}
	return width;
}

int ui_paragraph(struct ui *ui, const struct ui_font *font, int x, int y, int width, const char *text, uint32_t color,
                 int alpha)
{
	char line[200], candidate[200];
	int line_height = font->height + 2;

	line[0] = 0;
	while (*text)
	{
		const char *start = text;
		int size;

		while (*text && *text != ' ' && *text != '\n')
			text++;
		size = (int)(text - start);
		if (size > 80)
			size = 80;
		if (size)
		{
			size_t length = strlen(line);

			if (length + (size_t)size + 2 > sizeof(candidate))
				break;
			memcpy(candidate, line, length);
			if (length)
				candidate[length++] = ' ';
			memcpy(candidate + length, start, (size_t)size);
			candidate[length + (size_t)size] = 0;
			/* too wide: the line so far goes out, the word starts the next */
			if (line[0] && ui_text_width(font, candidate) > width)
			{
				ui_text(ui, font, x, y, line, color, alpha, UI_LEFT);
				y += line_height;
				memcpy(line, start, (size_t)size);
				line[size] = 0;
			}
			else
				memcpy(line, candidate, strlen(candidate) + 1);
		}
		if (*text == '\n')
		{
			ui_text(ui, font, x, y, line, color, alpha, UI_LEFT);
			y += line_height;
			line[0] = 0;
		}
		if (*text)
			text++;
	}
	if (line[0])
	{
		ui_text(ui, font, x, y, line, color, alpha, UI_LEFT);
		y += line_height;
	}
	return y;
}

/* ----- badges and icons */

void ui_button(struct ui *ui, float cx, float cy, float r, char which, int alpha)
{
	float s = r * 0.5f, t = r * 0.13f + 0.6f;

	ui_circle(ui, cx, cy, r, UI_RGB(22, 26, 34), alpha);
	ui_ring(ui, cx, cy, r - 0.6f, 1.2f, 0, 1, UI_RGB(80, 92, 110), alpha);
	switch (which)
	{
	case 't': /* green */
		ui_line(ui, cx, cy - s, cx - s * 0.95f, cy + s * 0.6f, t, UI_RGB(70, 214, 140), alpha);
		ui_line(ui, cx - s * 0.95f, cy + s * 0.6f, cx + s * 0.95f, cy + s * 0.6f, t, UI_RGB(70, 214, 140), alpha);
		ui_line(ui, cx + s * 0.95f, cy + s * 0.6f, cx, cy - s, t, UI_RGB(70, 214, 140), alpha);
		break;
	case 'c': /* red */
		ui_ring(ui, cx, cy, s * 0.85f, t, 0, 1, UI_RGB(255, 98, 98), alpha);
		break;
	case 'x': /* blue */
		ui_line(ui, cx - s * 0.75f, cy - s * 0.75f, cx + s * 0.75f, cy + s * 0.75f, t, UI_RGB(110, 170, 255), alpha);
		ui_line(ui, cx - s * 0.75f, cy + s * 0.75f, cx + s * 0.75f, cy - s * 0.75f, t, UI_RGB(110, 170, 255), alpha);
		break;
	default: /* pink square */
		ui_round_line(ui, cx - s * 0.75f, cy - s * 0.75f, s * 1.5f, s * 1.5f, 0.5f, t, UI_RGB(255, 130, 210), alpha);
		break;
	}
}

void ui_icon(struct ui *ui, enum ui_icon icon, float cx, float cy, float size, uint32_t color, float phase)
{
	float s = size * 0.5f, t = size * 0.085f + 0.5f;
	int k;

	switch (icon)
	{
	case UI_ICON_SHIELD:
		/* a shield: a rounded top, two sides meeting in a point, a tick inside */
		ui_line(ui, cx - s * 0.75f, cy - s * 0.6f, cx, cy - s * 0.85f, t, color, 255);
		ui_line(ui, cx, cy - s * 0.85f, cx + s * 0.75f, cy - s * 0.6f, t, color, 255);
		ui_line(ui, cx - s * 0.75f, cy - s * 0.6f, cx - s * 0.7f, cy + s * 0.1f, t, color, 255);
		ui_line(ui, cx + s * 0.75f, cy - s * 0.6f, cx + s * 0.7f, cy + s * 0.1f, t, color, 255);
		ui_line(ui, cx - s * 0.7f, cy + s * 0.1f, cx, cy + s * 0.9f, t, color, 255);
		ui_line(ui, cx + s * 0.7f, cy + s * 0.1f, cx, cy + s * 0.9f, t, color, 255);
		ui_line(ui, cx - s * 0.32f, cy, cx - s * 0.05f, cy + s * 0.28f, t, color, 255);
		ui_line(ui, cx - s * 0.05f, cy + s * 0.28f, cx + s * 0.38f, cy - s * 0.25f, t, color, 255);
		break;
	case UI_ICON_RESTORE:
		/* an arrow going round, back to the start */
		ui_ring(ui, cx, cy, s * 0.7f, t, 0.12f, 0.95f, color, 255);
		ui_line(ui, cx + s * 0.25f, cy - s * 0.95f, cx + s * 0.5f, cy - s * 0.55f, t, color, 255);
		ui_line(ui, cx + s * 0.5f, cy - s * 0.55f, cx + s * 0.05f, cy - s * 0.38f, t, color, 255);
		ui_line(ui, cx, cy, cx, cy - s * 0.35f, t, color, 255);
		ui_line(ui, cx, cy, cx + s * 0.28f, cy + s * 0.15f, t, color, 255);
		break;
	case UI_ICON_WIFI:
		/* arcs over a dot; phase lights them one by one (joining), or all (< 0) */
		ui_circle(ui, cx, cy + s * 0.55f, s * 0.13f, color, 255);
		for (k = 0; k < 3; k++)
		{
			int lit = phase < 0 || (int)(phase * 4) > k;

			ui_ring(ui, cx, cy + s * 0.55f, s * (0.42f + 0.34f * k), t, 0.875f, 1.125f, color, lit ? 255 : 70);
		}
		break;
	case UI_ICON_CHECK:
		ui_circle(ui, cx, cy, s, color, 255);
		ui_line(ui, cx - s * 0.42f, cy + s * 0.02f, cx - s * 0.1f, cy + s * 0.34f, s * 0.2f, UI_BG, 255);
		ui_line(ui, cx - s * 0.1f, cy + s * 0.34f, cx + s * 0.45f, cy - s * 0.3f, s * 0.2f, UI_BG, 255);
		break;
	case UI_ICON_WARN:
		ui_circle(ui, cx, cy, s, color, 255);
		ui_line(ui, cx, cy - s * 0.5f, cx, cy + s * 0.12f, s * 0.2f, UI_BG, 255);
		ui_circle(ui, cx, cy + s * 0.45f, s * 0.12f, UI_BG, 255);
		break;
	case UI_ICON_KEY:
		ui_ring(ui, cx - s * 0.35f, cy, s * 0.32f, t, 0, 1, color, 255);
		ui_line(ui, cx - s * 0.03f, cy, cx + s * 0.85f, cy, t, color, 255);
		ui_line(ui, cx + s * 0.55f, cy, cx + s * 0.55f, cy + s * 0.32f, t, color, 255);
		ui_line(ui, cx + s * 0.8f, cy, cx + s * 0.8f, cy + s * 0.25f, t, color, 255);
		break;
	case UI_ICON_SWITCH:
		/* a slide switch, its knob up (phase 1) or down (phase 0) */
		ui_round_line(ui, cx - s * 0.32f, cy - s * 0.9f, s * 0.64f, s * 1.8f, s * 0.3f, t, color, 255);
		ui_round(ui, cx - s * 0.2f, cy + (phase > 0.5f ? -s * 0.75f : s * 0.05f), s * 0.4f, s * 0.7f, s * 0.15f,
			color, 255);
		break;
	}
}

void ui_spinner(struct ui *ui, float cx, float cy, float r, uint32_t color, float phase)
{
	int k;

	for (k = 0; k < 8; k++)
	{
		float turn = k / 8.0f, age = phase - turn;

		age -= floorf(age);
		ui_circle(ui, cx + sinf(turn * 2 * PI) * r, cy - cosf(turn * 2 * PI) * r, r * 0.16f, color,
			(int)(255 * (1 - age * 0.85f)));
	}
}

void ui_progress(struct ui *ui, int x, int y, int w, int h, float done, float phase)
{
	ui_round(ui, (float)x, (float)y, (float)w, (float)h, h * 0.5f, UI_BG, 220);
	if (done >= 0)
		ui_round(ui, (float)x, (float)y, w * clampf(done, 0.02f, 1), (float)h, h * 0.5f, UI_ACCENT, 255);
	else
	{
		float at = x + (phase - floorf(phase)) * (w + w * 0.3f) - w * 0.3f;
		float left = at < x ? (float)x : at, right = at + w * 0.3f > x + w ? (float)(x + w) : at + w * 0.3f;

		if (right > left)
			ui_round(ui, left, (float)y, right - left, (float)h, h * 0.5f, UI_ACCENT, 255);
	}
}

/* ----- the backdrop: RemotePilot PSP's XMB background without its words
(ui_backdrop.c, baked by make_backdrop.py from art/make_xmb_art.py) */

extern const unsigned char ui_backdrop_rgb[UI_W * UI_H * 3];

void ui_background_make(uint32_t *out)
{
	int k;

	for (k = 0; k < UI_W * UI_H; k++)
		out[k] = UI_RGB(ui_backdrop_rgb[3 * k], ui_backdrop_rgb[3 * k + 1], ui_backdrop_rgb[3 * k + 2]);
}

/* a glint running along the backdrop's horizon (its ellipse in make_xmb_art:
the box -0.4w..1.4w, 0.70h..2.2h) */
void ui_horizon_glint(struct ui *ui, float phase)
{
	float turn = (phase - 0.5f) * 1.1f, cx = UI_W * 0.5f, cy = UI_H * 1.45f, rx = UI_W * 0.9f, ry = UI_H * 0.75f;
	float x = cx + rx * sinf(turn), y = cy - ry * cosf(turn);
	int k;

	for (k = 6; k > 0; k--)
		ui_circle(ui, x, y, 3.0f * k, UI_ACCENT, 26);
	ui_circle(ui, x, y, 2.2f, UI_TEXT, 255);
}

void ui_background(struct ui *ui, const uint32_t *background)
{
	int y;

	for (y = 0; y < UI_H; y++)
		memcpy(ui->pixels + y * ui->stride, background + y * UI_W, UI_W * sizeof(uint32_t));
}
