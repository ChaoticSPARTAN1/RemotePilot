/* rp2_device.h - the device side of RemotePilot's RP2 protocol (docs/PROTOCOL.md),
for the PSP and for the desktop simulator.

Portable C99: everything the platform owns (sockets, time, randomness,
HMAC-SHA256, the actions themselves) comes in through rp2_platform, so the
same parser and authenticator run on the PSP and in the host tests. One call
serves one connection: HELLO, CHALLENGE, one authenticated REQUEST, one
signed RESPONSE, then the caller closes the socket. */
#ifndef RP2_DEVICE_H
#define RP2_DEVICE_H

#include <stddef.h>

#define RP2_TOKEN_BYTES 32
#define RP2_NONCE_BYTES 16
#define RP2_MAX_REQUEST 8192u
#define RP2_MAX_APP_ID 32
#define RP2_MAX_KIND 16

struct rp2_config
{
	char app_id[RP2_MAX_APP_ID + 1];
	unsigned int port;
	unsigned char token[RP2_TOKEN_BYTES];
	int session_on;
};

/* bytes kept free before reply data: the response MAC is computed over a
short prefix and the data in one piece, without copying the data */
#define RP2_REPLY_HEADROOM 64u

/* what one action answers: the kind ("error" on refusal) and its bytes in the
platform's buffer. data must have RP2_REPLY_HEADROOM writable bytes before
it; capacity counts only what follows */
struct rp2_reply
{
	char kind[RP2_MAX_KIND + 1];
	unsigned char *data;
	size_t length, capacity;
};

struct rp2_platform
{
	void *context;
	/* the socket, with the platform's own deadline; return bytes read or
	written (> 0), 0 at the peer's close, < 0 on error or timeout */
	int (*recv)(void *context, int socket, void *buffer, size_t size);
	int (*send)(void *context, int socket, const void *buffer, size_t size);
	/* fresh unpredictable bytes for the nonce; 0 on success */
	int (*random)(void *context, unsigned char *out, size_t size);
	/* HMAC-SHA256 from a vetted implementation (never a new primitive) */
	void (*hmac_sha256)(const unsigned char *key, size_t key_size, const unsigned char *data, size_t size,
	                    unsigned char digest[32]);
	/* one bounded action; fills reply (kind defaults to the request's).
	Return 0, or < 0 to answer "error" with a generic message */
	int (*act)(void *context, const char *kind, const unsigned char *body, size_t size, struct rp2_reply *reply);
	/* NULL, or taken (on 1) once a request's MAC checks and given back (on 0)
	after its reply is sent: the reply's memory, shared with the device's own
	work. Never held while an unauthenticated peer is still talking */
	void (*hold)(void *context, int on);
};

/* parses the device config the viewer's setup writes: app_id=, port=,
token= (64 lowercase hex), session=on|off. 0 on success */
int rp2_config_parse(const char *text, size_t size, struct rp2_config *out);

/* a peer the device may answer: 10/8, 172.16/12, 192.168/16 and loopback
(the simulator). address in host byte order */
int rp2_private_ipv4(unsigned int address);

/* serves one connection; 0 when a signed response was sent, < 0 otherwise
(the caller closes the socket either way) */
int rp2_serve(const struct rp2_platform *platform, const struct rp2_config *config, int socket,
              struct rp2_reply *reply);

/* constant-time comparison of two equal-length byte strings */
int rp2_equal(const unsigned char *a, const unsigned char *b, size_t size);

#endif
