#!/bin/bash
#Author: Ahmad Tarraf
#Date  : 14.Aug.2022
#title : Load bar

SC="\033[s"  #Save cursor position
RC="\033[u"  #Restore cursor position
SA="\033[1A" #  Move the cursor up N lines: \033[<N>A
#Sk="\033[K" # Erase to end of line:
  

progress () {
  in=$1
  lines=$(tput lines);
  columns=$(tput cols);
  declare -i value=0
  value=$((in * columns / 100))
  s="[\033[0;36m" 

for ((progress_i=1; progress_i<$columns - 1  ; progress_i++));
  do
  if [ $progress_i -lt $value ]
    then
    s="$s#"
      else
    s="$s."
  fi
  if [ $progress_i -eq $((value -1)) ]
  then
  s="$s\033[0m"
  fi

  done
  s="$s]"

  lines=$(tput lines)

  #echo -e "\n$SA"; 
  echo -en $SC ; echo -en "\033[$lines;0f";  echo  -en "$s" ; echo -en $RC ;
}

function progress_clear() {
        echo -en $SC ; echo -en "\033[$lines;0f";  echo  -en "\033[0K\n" ; echo -en $RC ;
}

function echo_clear() {
        echo  -e "\033[K$1" ; 
}

#init
progress_lines=$(tput lines)
let progress_lines=$progress_lines-1
echo -en "\n"
echo -en $SC
echo -en "\033[0;${progress_lines}r"
echo -en $RC
echo -en $SA
progress 0
