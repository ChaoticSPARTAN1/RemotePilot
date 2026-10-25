// SPDX-License-Identifier: GPL-3.0-only
#pragma once
#include <cstdint>
#include <string>
#include <vector>

struct Title { uint64_t id; uint16_t version; };
namespace platform {
enum class UserPrompt { none, arm, approve, review };
struct Dashboard {
    bool recovery=false,listening=false,armed=false,autonomous=false,active=false;
    unsigned build=0,version=0;
    uint64_t done=0,total=0;
    std::string address,phase,target,hash,instruction,next;
    UserPrompt prompt=UserPrompt::none;
};
bool init();
void exit();
bool running();
uint64_t milliseconds();
std::string networkAddress();
unsigned keys(); // A=1, B=2, X=4, START=8, Y=16. HID cannot distinguish injection.
bool random(void*, size_t);
bool titles(std::vector<Title>&);
bool inspect(const std::string&, Title&, uint64_t& required);
uint64_t freeSpace();
bool startInstall();
bool writeInstall(uint64_t, const void*, size_t);
bool finishInstall();
bool cancelInstall();
bool prepareLaunch(uint64_t);
bool launch();
void display(const std::string&, const std::string&, UserPrompt=UserPrompt::none);
void dashboard(const Dashboard&);
}
