// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include <algorithm>
#include <cerrno>
#include <string>
namespace socket_io {
// Keep each SOC write below libctru's 0x2000 IPC-path boundary. Readiness
// includes the original absolute deadline; transient errors never renew it.
template<class Ready,class Write>
bool sendAll(const std::string& data,Ready ready,Write write) {
    size_t done=0;
    while(done<data.size()) {
        if(!ready())return false;
        const size_t count=std::min(size_t(4096),data.size()-done);
        const auto n=write(data.data()+done,count);
        if(n<0) {
            if(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK)continue;
            return false;
        }
        if(n==0||size_t(n)>count)return false;
        done+=size_t(n);
    }
    return true;
}
}
