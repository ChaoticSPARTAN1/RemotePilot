// SPDX-License-Identifier: GPL-3.0-only
// Exercise the production send loop without a console or network connection.
#include "socket_io.hpp"
#include <cassert>
#include <cstdio>
int main() {
    std::string expected(262144,'x'),received;
    unsigned calls=0;
    assert(socket_io::sendAll(expected,[](){return true;},[&](const char* p,size_t n)->int{
        assert(n<=4096);++calls;
        if(calls%5==1){errno=EAGAIN;return -1;}
        if(calls%7==1){errno=EINTR;return -1;}
        size_t sent=std::min(n,size_t(103));received.append(p,sent);return int(sent);
    }));
    assert(received==expected);
    unsigned remaining=5;
    assert(!socket_io::sendAll(expected,[&](){return remaining-- >0;},[](const char*,size_t)->int{errno=EWOULDBLOCK;return -1;}));
    assert(!socket_io::sendAll(expected,[](){return true;},[](const char*,size_t)->int{errno=EPIPE;return -1;}));
    assert(!socket_io::sendAll(expected,[](){return true;},[](const char*,size_t)->int{return 0;}));
    assert(!socket_io::sendAll(expected,[](){return true;},[](const char*,size_t n)->int{return int(n)+1;}));
    assert(socket_io::sendAll(std::string(),[](){return false;},[](const char*,size_t)->int{assert(false);return 0;}));
    std::puts("SOC send regression: bounded writes, partial progress, EINTR/EAGAIN, deadline and hard failures PASS");
}
