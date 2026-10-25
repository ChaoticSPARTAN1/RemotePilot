#include "sha256.hpp"

#include <cstdio>
#include <algorithm>
#include <cstring>
#include <vector>

namespace sha256 {

namespace {

constexpr uint32_t Rounds[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

uint32_t rotate(uint32_t value, int by)
{
    return (value >> by) | (value << (32 - by));
}

} // namespace

Hasher::Hasher()
    : state_{0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f,
             0x9b05688c, 0x1f83d9ab, 0x5be0cd19}
{
}

void Hasher::block(const uint8_t *data)
{
    uint32_t words[64];
    for (int index = 0; index < 16; ++index) {
        words[index] = static_cast<uint32_t>(data[index * 4]) << 24 |
                       static_cast<uint32_t>(data[index * 4 + 1]) << 16 |
                       static_cast<uint32_t>(data[index * 4 + 2]) << 8 |
                       static_cast<uint32_t>(data[index * 4 + 3]);
    }
    for (int index = 16; index < 64; ++index) {
        const uint32_t s0 = rotate(words[index - 15], 7) ^
                            rotate(words[index - 15], 18) ^
                            (words[index - 15] >> 3);
        const uint32_t s1 = rotate(words[index - 2], 17) ^
                            rotate(words[index - 2], 19) ^
                            (words[index - 2] >> 10);
        words[index] = words[index - 16] + s0 + words[index - 7] + s1;
    }
    uint32_t a = state_[0], b = state_[1], c = state_[2], d = state_[3];
    uint32_t e = state_[4], f = state_[5], g = state_[6], h = state_[7];
    for (int index = 0; index < 64; ++index) {
        const uint32_t s1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25);
        const uint32_t choice = (e & f) ^ (~e & g);
        const uint32_t first = h + s1 + choice + Rounds[index] + words[index];
        const uint32_t s0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22);
        const uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        const uint32_t second = s0 + majority;
        h = g;
        g = f;
        f = e;
        e = d + first;
        d = c;
        c = b;
        b = a;
        a = first + second;
    }
    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
}

void Hasher::update(const void *data, size_t size)
{
    const uint8_t *bytes = static_cast<const uint8_t *>(data);
    length_ += size;
    while (size > 0) {
        const size_t take = std::min(size, sizeof(buffer_) - buffered_);
        std::memcpy(buffer_ + buffered_, bytes, take);
        buffered_ += take;
        bytes += take;
        size -= take;
        if (buffered_ == sizeof(buffer_)) {
            block(buffer_);
            buffered_ = 0;
        }
    }
}

std::string Hasher::finishHex()
{
    const uint64_t bits = length_ * 8;
    const uint8_t pad = 0x80;
    update(&pad, 1);
    const uint8_t zero = 0;
    while (buffered_ != 56) {
        update(&zero, 1);
    }
    uint8_t lengthBytes[8];
    for (int index = 0; index < 8; ++index) {
        lengthBytes[index] = static_cast<uint8_t>(bits >> (56 - index * 8));
    }
    update(lengthBytes, sizeof(lengthBytes));

    static const char Digits[] = "0123456789abcdef";
    std::string hex;
    hex.reserve(64);
    for (uint32_t word : state_) {
        for (int shift = 28; shift >= 0; shift -= 4) {
            hex += Digits[(word >> shift) & 0xf];
        }
    }
    return hex;
}

std::string ofString(const std::string &data)
{
    Hasher hasher;
    hasher.update(data.data(), data.size());
    return hasher.finishHex();
}

std::string ofFile(const std::string &path)
{
    FILE *file = std::fopen(path.c_str(), "rb");
    if (file == nullptr) {
        return "";
    }
    Hasher hasher;
    std::vector<uint8_t> buffer(64 * 1024);
    bool ok = true;
    while (true) {
        const size_t got = std::fread(buffer.data(), 1, buffer.size(), file);
        if (got > 0) {
            hasher.update(buffer.data(), got);
        }
        if (got < buffer.size()) {
            ok = std::ferror(file) == 0;
            break;
        }
    }
    std::fclose(file);
    return ok ? hasher.finishHex() : "";
}

} // namespace sha256
