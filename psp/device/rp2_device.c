/* rp2_device.c - RP2's device side (rp2_device.h). Fixed buffers, bounded
lines, constant-time MAC checks; one exchange per connection. */
#include "rp2_device.h"

#include <stdio.h>
#include <string.h>

/* rp2_serve keeps the request body in one static buffer: one connection at a
time, from one listener thread */

#define HELLO_LIMIT 64
#define REQUEST_LIMIT 160
#define ID_DIGITS 10

static int hex_value(int c)
{
	if (c >= '0' && c <= '9')
		return c - '0';
	if (c >= 'a' && c <= 'f')
		return c - 'a' + 10;
	return -1;
}

static void hex_encode(const unsigned char *in, size_t size, char *out)
{
	static const char digits[] = "0123456789abcdef";
	size_t k;

	for (k = 0; k < size; k++)
	{
		out[2 * k] = digits[in[k] >> 4];
		out[2 * k + 1] = digits[in[k] & 15];
	}
	out[2 * size] = 0;
}

static int hex_decode(const char *in, unsigned char *out, size_t size)
{
	size_t k;

	for (k = 0; k < size; k++)
	{
		int high = hex_value((unsigned char)in[2 * k]), low = hex_value((unsigned char)in[2 * k + 1]);

		if (high < 0 || low < 0)
			return -1;
		out[k] = (unsigned char)(high << 4 | low);
	}
	return 0;
}

int rp2_equal(const unsigned char *a, const unsigned char *b, size_t size)
{
	unsigned char difference = 0;
	size_t k;

	for (k = 0; k < size; k++)
		difference |= (unsigned char)(a[k] ^ b[k]);
	return difference == 0;
}

int rp2_private_ipv4(unsigned int address)
{
	return (address >> 24) == 10 || (address >> 20) == ((172u << 4) | 1u) ||
		(address >> 16) == ((192u << 8) | 168u) || (address >> 24) == 127;
}

static int valid_app_id(const char *id)
{
	size_t k, size = strlen(id);

	if (size < 2 || size > RP2_MAX_APP_ID || id[0] < 'a' || id[0] > 'z')
		return 0;
	for (k = 1; k < size; k++)
		if (!((id[k] >= 'a' && id[k] <= 'z') || (id[k] >= '0' && id[k] <= '9') || id[k] == '-'))
			return 0;
	return 1;
}

int rp2_config_parse(const char *text, size_t size, struct rp2_config *out)
{
	size_t at = 0;
	int have_id = 0, have_port = 0, have_token = 0, have_session = 0;

	memset(out, 0, sizeof(*out));
	while (at < size)
	{
		char line[160];
		size_t length = 0;

		while (at < size && text[at] != '\n' && text[at] != '\r')
		{
			if (length + 1 >= sizeof(line))
				return -1;
			line[length++] = text[at++];
		}
		while (at < size && (text[at] == '\n' || text[at] == '\r'))
			at++;
		line[length] = 0;
		if (!length)
			continue;
		if (!strncmp(line, "app_id=", 7) && strlen(line + 7) <= RP2_MAX_APP_ID)
		{
			strcpy(out->app_id, line + 7);
			have_id = valid_app_id(out->app_id);
		}
		else if (!strncmp(line, "port=", 5))
		{
			const char *p = line + 5;
			unsigned long value = 0;

			if (!*p || strlen(p) > 5)
				return -1;
			for (; *p; p++)
			{
				if (*p < '0' || *p > '9')
					return -1;
				value = value * 10 + (unsigned long)(*p - '0');
			}
			if (value < 1024 || value > 65535)
				return -1;
			out->port = (unsigned int)value;
			have_port = 1;
		}
		else if (!strncmp(line, "token=", 6))
		{
			if (strlen(line + 6) != 2 * RP2_TOKEN_BYTES || hex_decode(line + 6, out->token, RP2_TOKEN_BYTES))
				return -1;
			have_token = 1;
		}
		else if (!strcmp(line, "session=on") || !strcmp(line, "session=off"))
		{
			out->session_on = line[9] == 'n';
			have_session = 1;
		}
		else
			return -1;
	}
	return have_id && have_port && have_token && have_session ? 0 : -1;
}

/* a line ending in \n, printable ASCII, at most limit bytes with the \n */
static int read_line(const struct rp2_platform *platform, int socket, char *line, size_t limit)
{
	size_t length = 0;

	while (length < limit)
	{
		char c;

		if (platform->recv(platform->context, socket, &c, 1) != 1)
			return -1;
		if (c == '\n')
		{
			line[length] = 0;
			return (int)length;
		}
		if (c < 32 || c > 126)
			return -1;
		line[length++] = c;
	}
	return -1;
}

static int read_exact(const struct rp2_platform *platform, int socket, unsigned char *out, size_t size)
{
	size_t done = 0;

	while (done < size)
	{
		int got = platform->recv(platform->context, socket, out + done, size - done);

		if (got <= 0)
			return -1;
		done += (size_t)got;
	}
	return 0;
}

static int send_all(const struct rp2_platform *platform, int socket, const void *data, size_t size)
{
	const unsigned char *at = data;

	while (size)
	{
		int sent = platform->send(platform->context, socket, at, size);

		if (sent <= 0)
			return -1;
		at += sent;
		size -= (size_t)sent;
	}
	return 0;
}

/* "<domain>\n<nonce>\n<id>\n<kind>\n" written just before data, then the MAC
over that prefix and the data together */
static void message_mac(const struct rp2_platform *platform, const struct rp2_config *config, const char *domain,
                        const unsigned char *nonce, const char *id, const char *kind, unsigned char *data, size_t size,
                        unsigned char mac[32])
{
	unsigned char *prefix;
	size_t length = strlen(domain) + 1 + RP2_NONCE_BYTES + 1 + strlen(id) + 1 + strlen(kind) + 1, at = 0;

	prefix = data - length;
	memcpy(prefix + at, domain, strlen(domain));
	at += strlen(domain);
	prefix[at++] = '\n';
	memcpy(prefix + at, nonce, RP2_NONCE_BYTES);
	at += RP2_NONCE_BYTES;
	prefix[at++] = '\n';
	memcpy(prefix + at, id, strlen(id));
	at += strlen(id);
	prefix[at++] = '\n';
	memcpy(prefix + at, kind, strlen(kind));
	at += strlen(kind);
	prefix[at++] = '\n';
	platform->hmac_sha256(config->token, RP2_TOKEN_BYTES, prefix, length + size, mac);
}

/* "RP2 REQUEST <id> <kind> <length> <mac>": fields checked as the host's
regular expressions define them */
static int parse_request(char *line, char *id, char *kind, size_t *length, unsigned char mac[32])
{
	char *field[4];
	char *at = line + 12;
	int count = 0;
	size_t k, size;

	if (strncmp(line, "RP2 REQUEST ", 12))
		return -1;
	field[count++] = at;
	for (; *at && count < 4; at++)
		if (*at == ' ')
		{
			*at = 0;
			field[count++] = at + 1;
		}
	if (count != 4 || strchr(field[3], ' '))
		return -1;
	size = strlen(field[0]);
	if (size < 1 || size > ID_DIGITS)
		return -1;
	for (k = 0; k < size; k++)
		if (field[0][k] < '0' || field[0][k] > '9')
			return -1;
	strcpy(id, field[0]);
	size = strlen(field[1]);
	if (size < 1 || size > RP2_MAX_KIND)
		return -1;
	for (k = 0; k < size; k++)
		if (field[1][k] < 'a' || field[1][k] > 'z')
			return -1;
	strcpy(kind, field[1]);
	size = strlen(field[2]);
	if (size < 1 || size > 8)
		return -1;
	*length = 0;
	for (k = 0; k < size; k++)
	{
		if (field[2][k] < '0' || field[2][k] > '9')
			return -1;
		*length = *length * 10 + (size_t)(field[2][k] - '0');
	}
	if (*length > RP2_MAX_REQUEST || strlen(field[3]) != 64)
		return -1;
	return hex_decode(field[3], mac, 32);
}

int rp2_serve(const struct rp2_platform *platform, const struct rp2_config *config, int socket,
              struct rp2_reply *reply)
{
	static unsigned char body_space[RP2_REPLY_HEADROOM + RP2_MAX_REQUEST + 1];
	unsigned char *body = body_space + RP2_REPLY_HEADROOM;
	char line[REQUEST_LIMIT + 1], id[ID_DIGITS + 1], kind[RP2_MAX_KIND + 1], text[160], hex[65];
	unsigned char nonce[RP2_NONCE_BYTES], mac[32], expected[32];
	size_t size, length;
	int failed;

	if (!config->session_on)
		return -1;
	/* 1-2: HELLO with our application, then a fresh nonce and our proof */
	if (read_line(platform, socket, line, HELLO_LIMIT) < 0 || strncmp(line, "RP2 HELLO ", 10) ||
		strcmp(line + 10, config->app_id))
		return -1;
	if (platform->random(platform->context, nonce, sizeof(nonce)))
		return -1;
	size = strlen(config->app_id);
	memcpy(text, "device\n", 7);
	memcpy(text + 7, config->app_id, size);
	text[7 + size] = '\n';
	memcpy(text + 8 + size, nonce, sizeof(nonce));
	platform->hmac_sha256(config->token, RP2_TOKEN_BYTES, (unsigned char *)text, 8 + size + sizeof(nonce), mac);
	memcpy(line, "RP2 CHALLENGE ", 14);
	hex_encode(nonce, sizeof(nonce), line + 14);
	line[14 + 32] = ' ';
	hex_encode(mac, 32, line + 47);
	line[47 + 64] = '\n';
	if (send_all(platform, socket, line, 48 + 64))
		return -1;
	/* 3-4: one request, its MAC checked before anything is done */
	if (read_line(platform, socket, line, REQUEST_LIMIT) < 0 || parse_request(line, id, kind, &length, mac))
		return -1;
	if (read_exact(platform, socket, body, length))
		return -1;
	message_mac(platform, config, "request", nonce, id, kind, body, length, expected);
	if (!rp2_equal(mac, expected, 32))
		return -1;
	body[length] = 0;
	if (platform->hold)
		platform->hold(platform->context, 1);
	strcpy(reply->kind, kind);
	reply->length = 0;
	if (!strcmp(kind, "error") || platform->act(platform->context, kind, body, length, reply) < 0 ||
		reply->length > reply->capacity)
	{
		static const char declined[] = "declined";

		strcpy(reply->kind, "error");
		memcpy(reply->data, declined, sizeof(declined) - 1);
		reply->length = sizeof(declined) - 1;
	}
	/* 5: the signed response, then the caller closes */
	message_mac(platform, config, "response", nonce, id, reply->kind, reply->data, reply->length, mac);
	hex_encode(mac, 32, hex);
	size = (size_t)snprintf(line, sizeof(line), "RP2 RESPONSE %s %s %lu %s\n", id, reply->kind,
		(unsigned long)reply->length, hex);
	failed = size >= sizeof(line) || send_all(platform, socket, line, size) ||
		send_all(platform, socket, reply->data, reply->length);
	if (platform->hold)
		platform->hold(platform->context, 0);
	return failed ? -1 : 0;
}
