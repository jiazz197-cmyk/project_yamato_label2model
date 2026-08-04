/**
 * Label Studio Open Source - State Registry
 *
 * This file registers core LSO project states with the state registry from app-common.
 *
 * The base registry (imported from @humansignal/app-common) provides:
 * - StateRegistry class and singleton instance
 * - StateType enum (INITIAL, IN_PROGRESS, ATTENTION, TERMINAL)
 * - Helper functions (getStateColorClass, formatStateName, etc.)
 *
 * LSO supports a simplified state model with 3 core project states:
 * - CREATED (initial state)
 * - ANNOTATION_IN_PROGRESS (work in progress)
 * - COMPLETED (terminal state)
 *
 * IMPORTANT: Import this file in your main.tsx or app initialization:
 * ```typescript
 * import './utils/state-registry-lso';
 * ```
 */

import { stateRegistry, StateType } from "@humansignal/app-common";

// ============================================================================
// Project States (LSO Core)
// ============================================================================

/**
 * LSO has a simplified state model with 3 core states.
 * LSE extends this with additional workflow states (review, arbitration, etc.)
 */
stateRegistry.registerBatch({
  CREATED: {
    type: StateType.INITIAL,
    label: "Created",
    tooltips: {
      project: "项目已创建，可以开始配置",
    },
  },

  ANNOTATION_IN_PROGRESS: {
    type: StateType.IN_PROGRESS,
    label: "进行中",
    tooltips: {
      project: "该项目正在进行标注工作",
      task: "任务正在被标注",
    },
  },

  COMPLETED: {
    type: StateType.TERMINAL,
    label: "Completed",
    tooltips: {
      project: "该项目的工作已全部完成",
      task: "任务已完成",
    },
  },
});

// ============================================================================
// Development Validation
// ============================================================================

/**
 * In development mode, verify all expected LSO states are properly registered.
 * This helps catch configuration issues early.
 */
if (process.env.NODE_ENV === "development") {
  const lsoStates = ["CREATED", "ANNOTATION_IN_PROGRESS", "COMPLETED"];

  const missingStates = lsoStates.filter((state) => !stateRegistry.isRegistered(state));

  if (missingStates.length > 0) {
    console.error("[LSO State Registry] Missing state registrations:", missingStates);
  } else {
    console.log("[LSO State Registry] ✅ All LSO states registered successfully");
    console.log(`[LSO State Registry] Registered ${lsoStates.length} LSO states`);
  }

  // Log all registered states for debugging
  if (process.env.DEBUG_STATE_REGISTRY) {
    console.log("[LSO State Registry] All registered states:", stateRegistry.getAllStates());
  }
}
