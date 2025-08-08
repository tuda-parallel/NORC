#!/bin/bash

source "$CONFIG_DIR/build_settings.sh"

print_info "Removing previous installation and temporary files"

rm -rf "$TMP_DIR"
rm -rf "$INSTALL_DIR"
