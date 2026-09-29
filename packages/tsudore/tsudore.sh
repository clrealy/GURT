#!/usr/bin/env bash
# tsudore — tsundere sudo. it's not like it wants to help you or anything.
# nyarch exclusive. baka.

set -u

pink=$'\e[38;5;211m'
red=$'\e[38;5;203m'
dim=$'\e[2m'
reset=$'\e[0m'

say() { printf '%s%s%s\n' "$pink" "$1" "$reset"; }
mad() { printf '%s%s%s\n' "$red" "$1" "$reset"; }

pick() { local arr=("$@"); printf '%s' "${arr[RANDOM % ${#arr[@]}]}"; }

# --- nyarch check ---
if ! grep -qi 'nyarch' /etc/os-release 2>/dev/null; then
  mad "h-huh?? you're not even on nyarch?!"
  mad "i only give root to catgirl distros. go use regular sudo, baka 😤"
  exit 1
fi

# --- no command given ---
if [ $# -eq 0 ]; then
  say "$(pick \
    "you called me for NOTHING?? unbelievable." \
    "...you just wanted to talk to me? w-whatever. 😳" \
    "usage: tsudore <command>. not that i care if you learn it.")"
  exit 1
fi

# --- intro line ---
say "$(pick \
  "ugh, fine. it's not like i WANTED to give you root or anything..." \
  "you again?? ...okay but only this once. baka." \
  "d-don't get the wrong idea! i'm only doing this bc the system needs it." \
  "hmph. you better not rm -rf anything, dummy.")"

# --- password check ---
if ! sudo -v 2>/dev/null; then
  mad "$(pick \
    "you forgot your OWN password?? i can't believe you. 🙄" \
    "wrong. obviously. do you even know who you are??" \
    "hmph! no root for you. try again when you remember, idiot.")"
  exit 1
fi

# --- spicy command reactions ---
case "$*" in
  *"rm -rf /"*|*"rm -rf /*"*)
    mad "ABSOLUTELY NOT. i'm not letting you delete me. i-i mean the system!!"
    exit 1 ;;
  *pacman*-Syu*|*yay*|*paru*)
    say "updating? ...fine. at least you take care of me. n-not that i noticed. 😳" ;;
  *reboot*|*shutdown*|*poweroff*)
    say "you're LEAVING?? ...w-whatever. see if i care. come back soon. 🥺" ;;
  *nano*|*vim*|*nvim*)
    say "editing system files? don't mess it up or i'm telling arch-chan." ;;
esac

# --- actually run it ---
sudo -- "$@"
status=$?

if [ $status -eq 0 ]; then
  say "$(pick \
    "there. done. you're welcome. n-not that you need to thank me! 💢" \
    "it worked. obviously. because i did it." \
    "hmph. you owe me one, dummy.")"
else
  mad "$(pick \
    "it failed?! that's YOUR fault, not mine!!" \
    "exit code $status... wow. amazing work. 🙄" \
    "don't look at me like that, your command was just bad.")"
fi

printf '%s(tsudore exited %s)%s\n' "$dim" "$status" "$reset"
exit $status
