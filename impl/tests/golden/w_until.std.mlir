// Generated from Semantic IR (lir_version 0.1, module t) — do not edit.
// RFC-0004 S4-S5: standard dialects (func, arith). See backend.py for the
// recorded deviation: the custom `lnpl` dialect is not yet registered.
module {
  func.func private @lnpl_step(!llvm.ptr, i32) -> i32
  func.func private @lnpl_effect(!llvm.ptr, !llvm.ptr) -> ()

  llvm.mlir.global internal constant @s0("load user\00")
  llvm.mlir.global internal constant @s1("RepositoryCall\00")
  llvm.mlir.global internal constant @s2("cache user\00")
  llvm.mlir.global internal constant @s3("CacheAccess\00")

  func.func @lnpl_run(%skip : i32, %counter : i64) -> i32 {
    %c0 = arith.constant 0 : i32
    %c1 = arith.constant 1 : i32
    %c10_i64 = arith.constant 10 : i64
    // step 1: load user
    %p1 = llvm.mlir.addressof @s0 : !llvm.ptr
    %i1 = arith.constant 1 : i32
    %r1 = func.call @lnpl_step(%p1, %i1) : (!llvm.ptr, i32) -> i32
    %k1_0 = llvm.mlir.addressof @s1 : !llvm.ptr
    func.call @lnpl_effect(%p1, %k1_0) : (!llvm.ptr, !llvm.ptr) -> ()
    // step 2: cache user  (guarded by `until` counter >= 10)
    %p2 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i2 = arith.constant 2 : i32
    %ucond2 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond2 {
      %r2 = func.call @lnpl_step(%p2, %i2) : (!llvm.ptr, i32) -> i32
      %k2_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p2, %k2_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 3: cache user  (guarded by `until` counter >= 10)
    %p3 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i3 = arith.constant 3 : i32
    %ucond3 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond3 {
      %r3 = func.call @lnpl_step(%p3, %i3) : (!llvm.ptr, i32) -> i32
      %k3_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p3, %k3_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 4: cache user  (guarded by `until` counter >= 10)
    %p4 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i4 = arith.constant 4 : i32
    %ucond4 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond4 {
      %r4 = func.call @lnpl_step(%p4, %i4) : (!llvm.ptr, i32) -> i32
      %k4_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p4, %k4_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 5: cache user  (guarded by `until` counter >= 10)
    %p5 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i5 = arith.constant 5 : i32
    %ucond5 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond5 {
      %r5 = func.call @lnpl_step(%p5, %i5) : (!llvm.ptr, i32) -> i32
      %k5_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p5, %k5_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 6: cache user  (guarded by `until` counter >= 10)
    %p6 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i6 = arith.constant 6 : i32
    %ucond6 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond6 {
      %r6 = func.call @lnpl_step(%p6, %i6) : (!llvm.ptr, i32) -> i32
      %k6_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p6, %k6_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 7: cache user  (guarded by `until` counter >= 10)
    %p7 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i7 = arith.constant 7 : i32
    %ucond7 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond7 {
      %r7 = func.call @lnpl_step(%p7, %i7) : (!llvm.ptr, i32) -> i32
      %k7_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p7, %k7_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 8: cache user  (guarded by `until` counter >= 10)
    %p8 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i8 = arith.constant 8 : i32
    %ucond8 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond8 {
      %r8 = func.call @lnpl_step(%p8, %i8) : (!llvm.ptr, i32) -> i32
      %k8_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p8, %k8_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 9: cache user  (guarded by `until` counter >= 10)
    %p9 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i9 = arith.constant 9 : i32
    %ucond9 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond9 {
      %r9 = func.call @lnpl_step(%p9, %i9) : (!llvm.ptr, i32) -> i32
      %k9_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p9, %k9_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 10: cache user  (guarded by `until` counter >= 10)
    %p10 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i10 = arith.constant 10 : i32
    %ucond10 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond10 {
      %r10 = func.call @lnpl_step(%p10, %i10) : (!llvm.ptr, i32) -> i32
      %k10_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p10, %k10_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 11: cache user  (guarded by `until` counter >= 10)
    %p11 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i11 = arith.constant 11 : i32
    %ucond11 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond11 {
      %r11 = func.call @lnpl_step(%p11, %i11) : (!llvm.ptr, i32) -> i32
      %k11_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p11, %k11_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 12: cache user  (guarded by `until` counter >= 10)
    %p12 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i12 = arith.constant 12 : i32
    %ucond12 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond12 {
      %r12 = func.call @lnpl_step(%p12, %i12) : (!llvm.ptr, i32) -> i32
      %k12_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p12, %k12_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 13: cache user  (guarded by `until` counter >= 10)
    %p13 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i13 = arith.constant 13 : i32
    %ucond13 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond13 {
      %r13 = func.call @lnpl_step(%p13, %i13) : (!llvm.ptr, i32) -> i32
      %k13_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p13, %k13_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 14: cache user  (guarded by `until` counter >= 10)
    %p14 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i14 = arith.constant 14 : i32
    %ucond14 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond14 {
      %r14 = func.call @lnpl_step(%p14, %i14) : (!llvm.ptr, i32) -> i32
      %k14_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p14, %k14_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 15: cache user  (guarded by `until` counter >= 10)
    %p15 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i15 = arith.constant 15 : i32
    %ucond15 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond15 {
      %r15 = func.call @lnpl_step(%p15, %i15) : (!llvm.ptr, i32) -> i32
      %k15_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p15, %k15_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 16: cache user  (guarded by `until` counter >= 10)
    %p16 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i16 = arith.constant 16 : i32
    %ucond16 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond16 {
      %r16 = func.call @lnpl_step(%p16, %i16) : (!llvm.ptr, i32) -> i32
      %k16_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p16, %k16_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    // step 17: cache user  (guarded by `until` counter >= 10)
    %p17 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i17 = arith.constant 17 : i32
    %ucond17 = arith.cmpi slt, %counter, %c10_i64 : i64
    scf.if %ucond17 {
      %r17 = func.call @lnpl_step(%p17, %i17) : (!llvm.ptr, i32) -> i32
      %k17_0 = llvm.mlir.addressof @s3 : !llvm.ptr
      func.call @lnpl_effect(%p17, %k17_0) : (!llvm.ptr, !llvm.ptr) -> ()
    }
    return %c0 : i32
  }
}
