; ---------------------------------------------------------------------------
; crt0.s -- TARA16 C start-up code. The driver places it first, at address 0
; (the reset PC). __stack_top is supplied by the driver (default 0x5FE: the
; stack grows down from just below the keyboard byte 0x5FF, leaving the
; 0x600-0x7FF framebuffer untouched).
;
; main()'s return value is left in R0 when the CPU halts.
; In the TARA Studio (.tara) version of the program the CALL below targets a
; generated __init routine that first stores the initialised data, then
; jumps to main; addresses are otherwise identical.
; ---------------------------------------------------------------------------
        .init
        .keep
_start:
        LA   R7, __stack_top
__crt0_call:
        CALL main
        HLT
