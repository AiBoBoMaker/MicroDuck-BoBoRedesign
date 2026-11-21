#!/bin/bash
# TLV320AIC3104 mixer setup. The kernel codec driver handles PLL / DAC / line
# output configuration via the devicetree overlay; this script only applies the
# default mixer levels and microphone routing on top.

sleep 2

# The ALSA card may not be registered immediately after boot — retry a few
# times if amixer can't find it yet. The window is generous because on the
# Radxa the card probe is deferred until the DKMS codec module autoloads.
for i in $(seq 1 15); do
    if amixer -c aic3104 info >/dev/null 2>&1; then
        # Speaker path: the speaker amp hangs off the codec's line outputs
        # (LEFT_LOP/RIGHT_LOP). Control names differ by driver build:
        # Radxa/DKMS uses 'PCM Playback Volume' / 'Line Playback Switch';
        # mainline tlv320aic3x on OPi uses the short 'PCM' / 'Line' names.
        if amixer -c aic3104 cset name='PCM Playback Volume' 127,127 >/dev/null 2>&1; then
            amixer -c aic3104 cset name='Line DAC Playback Volume' 118,118 >/dev/null
            amixer -c aic3104 cset name='Line Playback Switch'     on,on   >/dev/null
            amixer -c aic3104 cset name='Line Playback Volume'     9,9     >/dev/null
        else
            amixer -c aic3104 sset 'PCM' 100% >/dev/null
            amixer -c aic3104 sset 'Line DAC' 100% >/dev/null
            amixer -c aic3104 sset 'Line' 100% unmute >/dev/null
            amixer -c aic3104 sset 'Left Line Mixer DACL1' on >/dev/null 2>&1 || true
            amixer -c aic3104 sset 'Right Line Mixer DACR1' on >/dev/null 2>&1 || true
            amixer -c aic3104 sset 'Left DAC Mux' 'DAC_L1' >/dev/null 2>&1 || true
            amixer -c aic3104 sset 'Right DAC Mux' 'DAC_R1' >/dev/null 2>&1 || true
        fi

        # HAT schematic: onboard analog MEMS → series R → AIC3104 pin 16 = MIC2R.
        # (AIC3104 has no MIC3 ball; ALSA "Mic3R" on compatible ti,tlv320aic3x is the
        # same MIC3LR_* register bit that Mic2R uses on ti,tlv320aic3104.)
        # Route ONLY into the Right PGA. Do not also dump Mic2R into Left.
        for side in Left Right; do
            for inp in Mic3L Mic3R Mic2L Mic2R Line1L Line1R Line2L Line2R; do
                amixer -c aic3104 sset "$side PGA Mixer $inp" off >/dev/null 2>&1 || true
            done
        done
        amixer -c aic3104 sset 'Right PGA Mixer Mic2R' on >/dev/null 2>&1 \
            || amixer -c aic3104 sset 'Right PGA Mixer Mic3R' on >/dev/null

        amixer -c aic3104 cset name='PGA Capture Switch' on,on >/dev/null 2>&1 \
            || amixer -c aic3104 sset 'PGA' unmute >/dev/null 2>&1 || true
        # Prefer right PGA gain; left can stay low — mic is not on Left.
        amixer -c aic3104 cset name='PGA Capture Volume' 40,70 >/dev/null 2>&1 \
            || amixer -c aic3104 sset 'PGA' 50% >/dev/null 2>&1 || true
        amixer -c aic3104 sset 'AGC' off >/dev/null 2>&1 || true

        # Orange Pi H616 AHUB crossbar (playback + capture).
        amixer -c ahubdam sset 'I2S0 Src Select' 'APBIF_TXDIF0' >/dev/null 2>&1 || true
        amixer -c ahubdam sset 'APBIF0 Src Select' 'I2S0_TXDIF' >/dev/null 2>&1 || true

        echo "TLV320AIC3104 mixer levels set (MIC2R/pin16 → Right PGA only)"
        break
    fi
    sleep 1
done
