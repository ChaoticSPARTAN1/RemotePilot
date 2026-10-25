#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

// SHA-256, for checking downloaded updates against the checksums published
// with each release.
namespace sha256 {

class Hasher {
public:
    Hasher();
    void update(const void *data, size_t size);
    // The digest as 64 lowercase hex digits. The hasher is spent afterwards.
    std::string finishHex();

private:
    void block(const uint8_t *data);

    uint32_t state_[8];
    uint8_t buffer_[64];
    size_t buffered_ = 0;
    uint64_t length_ = 0;
};

std::string ofString(const std::string &data);
// Hashes the file at path. Returns "" when it cannot be read.
std::string ofFile(const std::string &path);

} // namespace sha256
