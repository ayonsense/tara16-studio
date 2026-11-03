; ---------------------------------------------------------------------------
; libtara16.s -- TARA16 C runtime helpers (called by compiler-generated code)
;
; Every routine is its own .chunk: the linker keeps only the ones a program
; actually calls. Convention (tara16-abi0): arguments in R0, R1, R2; result
; in R0; R0-R2 and R6 may be clobbered; R3-R5 are preserved.
; ---------------------------------------------------------------------------

; ---- __mulhi3: R0 = R0 * R1 (mod 2^16), shift-and-add ----------------------
; Used only with -mno-mul (the TTL board has no multiplier).
        .text
        .chunk __mulhi3
__mulhi3:
        PUSH R3
        MOV  R2, R0             ; R2 = multiplicand (doubles each step)
        LIL  R0, 0              ; R0 = product
__mulhi3_loop:
        BZ   R1, __mulhi3_done
        MOV  R3, R1
        SHL  R3, 15             ; isolate bit 0 of the multiplier
        BZ   R3, __mulhi3_skip
        ADD  R0, R0, R2
__mulhi3_skip:
        ADD  R2, R2, R2
        SHR  R1, 1
        JMP  __mulhi3_loop
__mulhi3_done:
        POP  R3
        RET

; ---- __udivmodhi4: R0 = R0 / R1, R1 = R0 % R1 (unsigned) --------------------
; Restoring division, one quotient bit per iteration. TARA16 has no unsigned
; compare, so r <u d is computed as (r ^ 0x8000) < (d ^ 0x8000) with SLT.
; Division by zero gives q = 0xFFFF, r = n (no trap).
        .text
        .chunk __udivmodhi4
__udivmodhi4:
        PUSH R6
        PUSH R5
        PUSH R4
        PUSH R3
        LIL  R6, 0
        LIH  R6, 0x80           ; R6 = 0x8000
        XOR  R5, R1, R6         ; R5 = d ^ 0x8000
        LIL  R2, 0              ; R2 = r
        LIL  R3, 16             ; R3 = bit counter
__udivmodhi4_loop:
        BN   R2, __udivmodhi4_big
        ADD  R2, R2, R2         ; r = 2r + msb(n)
        BN   R0, __udivmodhi4_one
        JMP  __udivmodhi4_cmp
__udivmodhi4_one:
        ADDI R2, 1
__udivmodhi4_cmp:
        ADD  R0, R0, R0         ; n <<= 1 (next quotient bit enters at bit 0)
        XOR  R4, R2, R6
        SLT  R4, R4, R5         ; R4 = (r <u d)
        BZ   R4, __udivmodhi4_sub
        JMP  __udivmodhi4_next
__udivmodhi4_big:               ; r >= 0x8000: 2r+b > 0xFFFF >= d
        ADD  R2, R2, R2
        BN   R0, __udivmodhi4_one2
        JMP  __udivmodhi4_sh2
__udivmodhi4_one2:
        ADDI R2, 1
__udivmodhi4_sh2:
        ADD  R0, R0, R0
__udivmodhi4_sub:
        SUB  R2, R2, R1         ; r -= d
        ADDI R0, 1              ; quotient bit = 1
__udivmodhi4_next:
        ADDI R3, -1
        BZ   R3, __udivmodhi4_done
        JMP  __udivmodhi4_loop
__udivmodhi4_done:
        MOV  R1, R2
        POP  R3
        POP  R4
        POP  R5
        POP  R6
        RET

        .text
        .chunk __udivhi3
__udivhi3:                      ; R0 = R0 / R1 (unsigned)
        PUSH R6
        CALL __udivmodhi4
        POP  R6
        RET

        .text
        .chunk __umodhi3
__umodhi3:                      ; R0 = R0 % R1 (unsigned)
        PUSH R6
        CALL __udivmodhi4
        MOV  R0, R1
        POP  R6
        RET

; ---- signed division: truncate toward zero; remainder has the dividend's sign
        .text
        .chunk __divhi3
__divhi3:                       ; R0 = R0 / R1 (signed)
        PUSH R6
        PUSH R3
        XOR  R3, R0, R1         ; R3 bit 15 = sign of the quotient
        BN   R0, __divhi3_na
        JMP  __divhi3_a
__divhi3_na:
        NOT  R0, R0
        ADDI R0, 1
__divhi3_a:
        BN   R1, __divhi3_nb
        JMP  __divhi3_b
__divhi3_nb:
        NOT  R1, R1
        ADDI R1, 1
__divhi3_b:
        CALL __udivmodhi4
        BN   R3, __divhi3_nq
        JMP  __divhi3_out
__divhi3_nq:
        NOT  R0, R0
        ADDI R0, 1
__divhi3_out:
        POP  R3
        POP  R6
        RET

        .text
        .chunk __modhi3
__modhi3:                       ; R0 = R0 % R1 (signed)
        PUSH R6
        PUSH R3
        MOV  R3, R0             ; R3 bit 15 = sign of the dividend
        BN   R0, __modhi3_na
        JMP  __modhi3_a
__modhi3_na:
        NOT  R0, R0
        ADDI R0, 1
__modhi3_a:
        BN   R1, __modhi3_nb
        JMP  __modhi3_b
__modhi3_nb:
        NOT  R1, R1
        ADDI R1, 1
__modhi3_b:
        CALL __udivmodhi4
        MOV  R0, R1
        BN   R3, __modhi3_nr
        JMP  __modhi3_out
__modhi3_nr:
        NOT  R0, R0
        ADDI R0, 1
__modhi3_out:
        POP  R3
        POP  R6
        RET

; ---- variable shifts: R0 = R0 <</>> R1 (TARA16 shifts by immediates only) ----
        .text
        .chunk __ashlhi3
__ashlhi3:
        BZ   R1, __ashlhi3_done
__ashlhi3_loop:
        ADD  R0, R0, R0
        ADDI R1, -1
        BZ   R1, __ashlhi3_done
        JMP  __ashlhi3_loop
__ashlhi3_done:
        RET

        .text
        .chunk __lshrhi3
__lshrhi3:
        BZ   R1, __lshrhi3_done
__lshrhi3_loop:
        SHR  R0, 1
        ADDI R1, -1
        BZ   R1, __lshrhi3_done
        JMP  __lshrhi3_loop
__lshrhi3_done:
        RET

        .text
        .chunk __ashrhi3
__ashrhi3:                      ; arithmetic: ~((~x) >> n) for negative x
        BZ   R1, __ashrhi3_done
        BN   R0, __ashrhi3_neg
__ashrhi3_pos:
        SHR  R0, 1
        ADDI R1, -1
        BZ   R1, __ashrhi3_done
        JMP  __ashrhi3_pos
__ashrhi3_neg:
        NOT  R0, R0
__ashrhi3_nloop:
        SHR  R0, 1
        ADDI R1, -1
        BZ   R1, __ashrhi3_nout
        JMP  __ashrhi3_nloop
__ashrhi3_nout:
        NOT  R0, R0
__ashrhi3_done:
        RET

; ---- block copy / clear (large struct assignment, big local initialisers) --
        .text
        .chunk __memcpy
__memcpy:                       ; copy R2 bytes from [R1] to [R0]
        PUSH R3
__memcpy_loop:
        BZ   R2, __memcpy_done
        LDB  R3, 0(R1)
        STB  R3, 0(R0)
        ADDI R0, 1
        ADDI R1, 1
        ADDI R2, -1
        JMP  __memcpy_loop
__memcpy_done:
        POP  R3
        RET

        .text
        .chunk __memclr
__memclr:                       ; clear R2 bytes at [R0]
        LIL  R1, 0
__memclr_loop:
        BZ   R2, __memclr_done
        STB  R1, 0(R0)
        ADDI R0, 1
        ADDI R2, -1
        JMP  __memclr_loop
__memclr_done:
        RET

; ---- __icall: call through a function pointer ------------------------------
; TARA16's only indirect jump is RET (PC = R6). The caller pushes the target
; and does CALL __icall; we swap the pushed target with our return address,
; jump to the target's entry stub (__ind_f: POP R6), which recovers the
; return address and falls into f. Arguments in R0-R2 pass through intact.
        .text
        .chunk __icall
__icall:
        PUSH R3
        LDW  R3, 2(R7)          ; R3 = target (stub address)
        STW  R6, 2(R7)          ; replace it with our return address
        MOV  R6, R3
        POP  R3
        RET                     ; -> __ind_f

; ---- shared function epilogues ---------------------------------------------
; The compiler ends a function with `JMP __epi_rN` instead of its own
; POP R5 / POP R4 / POP R3 / POP R6 / RET tail when several functions in the
; program can share it (it only does so when that saves space).
        .text
        .chunk __epi
__epi_r5:
        POP  R5
__epi_r4:
        POP  R4
__epi_r3:
        POP  R3
__epi_lr:
        POP  R6
        RET

        .text
        .chunk __lepi
__lepi_r5:
        POP  R5
__lepi_r4:
        POP  R4
__lepi_r3:
        POP  R3
        RET
