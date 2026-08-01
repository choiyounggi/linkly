// Generated from Semantic IR (lir_version 0.1, module login) — do not edit.
// RFC-0004 S4-S5: standard dialects (func, arith). See backend.py for the
// recorded deviation: the custom `lnpl` dialect is not yet registered.
module {
  func.func private @lnpl_step(!llvm.ptr, i32) -> i32
  func.func private @lnpl_effect(!llvm.ptr, !llvm.ptr) -> ()

  llvm.mlir.global internal constant @s0("validate input\00")
  llvm.mlir.global internal constant @s1("Validation\00")
  llvm.mlir.global internal constant @s2("authenticate\00")
  llvm.mlir.global internal constant @s3("RepositoryCall\00")
  llvm.mlir.global internal constant @s4("cache user\00")
  llvm.mlir.global internal constant @s5("CacheAccess\00")
  llvm.mlir.global internal constant @s6("generate token\00")
  llvm.mlir.global internal constant @s7("audit login\00")
  llvm.mlir.global internal constant @s8("return token\00")

  func.func @lnpl_run(%skip : i32) -> i32 {
    %c0 = arith.constant 0 : i32
    %c1 = arith.constant 1 : i32
    // step 1: validate input
    %p1 = llvm.mlir.addressof @s0 : !llvm.ptr
    %i1 = arith.constant 1 : i32
    %r1 = func.call @lnpl_step(%p1, %i1) : (!llvm.ptr, i32) -> i32
    %k1_0 = llvm.mlir.addressof @s1 : !llvm.ptr
    func.call @lnpl_effect(%p1, %k1_0) : (!llvm.ptr, !llvm.ptr) -> ()
    // step 2: authenticate
    %p2 = llvm.mlir.addressof @s2 : !llvm.ptr
    %i2 = arith.constant 2 : i32
    %r2 = func.call @lnpl_step(%p2, %i2) : (!llvm.ptr, i32) -> i32
    %k2_0 = llvm.mlir.addressof @s3 : !llvm.ptr
    func.call @lnpl_effect(%p2, %k2_0) : (!llvm.ptr, !llvm.ptr) -> ()
    // step 3: cache user
    %p3 = llvm.mlir.addressof @s4 : !llvm.ptr
    %i3 = arith.constant 3 : i32
    %r3 = func.call @lnpl_step(%p3, %i3) : (!llvm.ptr, i32) -> i32
    %k3_0 = llvm.mlir.addressof @s5 : !llvm.ptr
    func.call @lnpl_effect(%p3, %k3_0) : (!llvm.ptr, !llvm.ptr) -> ()
    // step 4: generate token
    %p4 = llvm.mlir.addressof @s6 : !llvm.ptr
    %i4 = arith.constant 4 : i32
    %r4 = func.call @lnpl_step(%p4, %i4) : (!llvm.ptr, i32) -> i32
    // step 5: audit login
    %p5 = llvm.mlir.addressof @s7 : !llvm.ptr
    %i5 = arith.constant 5 : i32
    %r5 = func.call @lnpl_step(%p5, %i5) : (!llvm.ptr, i32) -> i32
    // step 6: return token
    %p6 = llvm.mlir.addressof @s8 : !llvm.ptr
    %i6 = arith.constant 6 : i32
    %r6 = func.call @lnpl_step(%p6, %i6) : (!llvm.ptr, i32) -> i32
    return %c0 : i32
  }
}
