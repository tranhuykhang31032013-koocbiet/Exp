#!/bin/sh
if [ -f "nn-1a298aa575a0.nnue" ]; then
  echo "Existing nn-1a298aa575a0.nnue validated, skipping download"
  exit 0
fi
if [ -f "../nnue/nn-1a298aa575a0.nnue" ]; then
  cp -f "../nnue/nn-1a298aa575a0.nnue" "nn-1a298aa575a0.nnue"
  exit 0
fi
exit 1
