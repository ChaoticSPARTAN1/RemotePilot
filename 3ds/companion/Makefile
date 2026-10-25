.SUFFIXES:
ifeq ($(strip $(DEVKITARM)),)
$(error Set DEVKITARM to devkitPro/devkitARM)
endif
TOPDIR ?= $(CURDIR)
include $(DEVKITARM)/3ds_rules
VARIANT ?= companion
ifeq ($(VARIANT),updater)
TARGET := RemotePilotUpdater
BUILD := build-updater
APP_TITLE := RemotePilot Updater
VARIANT_FLAGS := -DRPH_UPDATER
else
TARGET := RemotePilotHomebrew
BUILD := build
APP_TITLE := RemotePilot Homebrew
endif
SOURCES := source
APP_DESCRIPTION := Private verified deployment companion
APP_AUTHOR := RemotePilot
ARCH := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft
CFLAGS := -g -Wall -Wextra -O2 -mword-relocations -ffunction-sections $(ARCH) $(INCLUDE) -D__3DS__ $(VARIANT_FLAGS)
CXXFLAGS := $(CFLAGS) -fno-rtti -fno-exceptions -std=gnu++17
ASFLAGS := -g $(ARCH)
LDFLAGS := -specs=3dsx.specs -g $(ARCH) -Wl,-Map,$(notdir $*.map)
LIBS := -lctru -lm
LIBDIRS := $(CTRULIB)
ifneq ($(BUILD),$(notdir $(CURDIR)))
export OUTPUT := $(CURDIR)/$(TARGET)
export TOPDIR := $(CURDIR)
export VPATH := $(CURDIR)/source
export DEPSDIR := $(CURDIR)/$(BUILD)
export LD := $(CXX)
export OFILES := main.o platform.o sha256.o screen_banner.bin.o
export INCLUDE := -I$(CURDIR)/source $(foreach dir,$(LIBDIRS),-I$(dir)/include) -I$(CURDIR)/$(BUILD)
export LIBPATHS := $(foreach dir,$(LIBDIRS),-L$(dir)/lib)
export _3DSXDEPS := $(OUTPUT).smdh
export APP_ICON := $(CURDIR)/$(BUILD)/icon.png
export _3DSXFLAGS := --smdh=$(OUTPUT).smdh
.PHONY: all
all: $(BUILD)
	@$(MAKE) --no-print-directory -C $(BUILD) -f $(CURDIR)/Makefile
$(BUILD):
	@mkdir -p $@
else
$(OUTPUT).3dsx: $(OUTPUT).elf $(OUTPUT).smdh
$(OUTPUT).elf: $(OFILES)
platform.o: screen_banner_bin.h
screen_banner.bin.o screen_banner_bin.h: screen_banner.bin
	@$(bin2o)
-include $(DEPSDIR)/*.d
endif
