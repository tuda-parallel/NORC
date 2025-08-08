#!/bin/bash

# Ignore any user locale settings
export LC_ALL=C

# silent versions of pushd and popd
pushd() {
  # not adding "command" here would lead to recursion
  command pushd "$@" > /dev/null
}

popd() {
  # not adding "command" here would lead to recursion
  command popd > /dev/null
}

# variously colored message printing functions
print_error() {
  echo -e "\e[0;31mERROR: $1\e[0m"
}

print_warning() {
  echo -e "\e[0;33mWARNING: $1\e[0m"
}

print_success() {
  echo -e "\e[1;32m$1\e[0m"
}

print_info() {
  echo -e "\e[36m$1\e[0m"
}

# exit functions for scripts
# these assume that pushd is only used at the start of the script.
exit_failure() {
  print_error "$1"
  popd
  exit 1
}

exit_success() {
  print_success "$1"
  popd
  exit 0
}

# checks if an error has occurred and exits if it has
check_failure() {
  if [ $? -ne 0 ]; then
    exit_failure "$1"
  fi
}

# checks if an error has occurred and prints a warning if it has
check_warn() {
  if [ $? -ne 0 ]; then
    print_warning "$1"
  fi
}

# turns a relative path variable into an absolute one
# absolute paths stay the same
globalize() {
  pushd "${!1}"
  check_failure "${!1}: No such directory"
  export ${1}=`pwd`
  popd
}

# appends an empty line if missing
# $1: file to be fixed
ensure_newline() {
  # If the last line is not empty, add another one
  # (doesn't work with empty files but these don't contain much configuration anyway.)
  if [ ! -z "$(tail -c 1 "$1")" ]; then
    echo "" >> "$1"
  fi
}

# outputs the n-th parameter
# $1: n (position of the positional argument)
# $2 - ${!#}: list of positional arguments
get_positional() {
  
  local pos=$1
  shift
  if [ $# -lt $pos ]; then
    return 1
  fi
  echo ${!pos}
  return 0
}

# outputs the number of arguments passed to this function
get_arg_count() {
  echo $#
}

python_version=$(python3 --version 2>&1)
if [ $? -eq 0 ]; then
  python_cmd="python3"
else
  python_version=$(python --version)
  if [ $? -eq 0 ]; then
    case $python_version in
      "Python 3"*)
        python_cmd="python";;
      *)
        echo "Python 3 is required." 1>&2
        exit 1;;
    esac
  else
    echo "Python could not be found." 1>&2
    exit 1
  fi
fi

export python_cmd