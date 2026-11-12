#!/bin/sh
case "$(uname -m 2>/dev/null)" in
  aarch64|arm64) printf 'armv8-dotprod\n' ;;
  x86_64)        printf 'x86-64-avx2\n' ;;
  *)             printf 'general-64\n' ;;
esac
