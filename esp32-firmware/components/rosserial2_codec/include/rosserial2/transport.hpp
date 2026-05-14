// Abstract transport interface for firmware. Mirrors the Python
// Transport protocol: read up to N bytes (non-blocking), write
// exactly N bytes, name yourself for logs. No exceptions; errors
// return zero / negative.

#pragma once

#include <cstddef>
#include <cstdint>

namespace rosserial2 {

class Transport {
public:
    Transport() = default;
    virtual ~Transport() = default;

    Transport(const Transport&) = delete;
    Transport& operator=(const Transport&) = delete;

    /// Read up to ``cap`` bytes into ``buf``. Returns the number of
    /// bytes actually read (0 if none available right now), or
    /// ``SIZE_MAX`` to signal an unrecoverable transport error.
    virtual std::size_t read(std::uint8_t* buf, std::size_t cap) noexcept = 0;

    /// Write all of ``data``. Returns true on success, false on
    /// transport error.
    virtual bool write(const std::uint8_t* data, std::size_t len) noexcept = 0;

    /// Identify the transport for logs.
    virtual const char* name() const noexcept = 0;

    static constexpr std::size_t ErrorSentinel = static_cast<std::size_t>(-1);
};

}  // namespace rosserial2
