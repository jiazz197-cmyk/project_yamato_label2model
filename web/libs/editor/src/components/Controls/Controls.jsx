import { inject, observer } from "mobx-react";
import { CheckCircleOutlined, CheckOutlined } from "@ant-design/icons";

import Hint from "../Hint/Hint";
import { DraftPanel } from "../Annotations/Annotations";
import styles from "./Controls.module.css";
import { Button, Tooltip } from "@humansignal/ui";
import { IconInfoOutline } from "@humansignal/icons";
import { cn } from "../../utils/bem";

export default inject("store")(
  observer(({ item, store }) => {
    /**
     * Buttons of Controls
     */
    const buttons = {
      skip: "",
      update: "",
      submit: "",
    };

    const { userGenerate, sentUserGenerate, versions } = item;
    const { enableHotkeys, enableTooltips } = store.settings;

    /**
     * Task information
     */
    let taskInformation;
    const taskInfoClassName = cn("task-info").toClassName();
    const skipButtonClassName = cn("skip-btn").toClassName();
    const submitButtonClassName = cn("submit-btn").toClassName();
    const updateButtonClassName = cn("update-btn").toClassName();

    if (store.task) {
      taskInformation = <h4 className={`${styles.task} ${taskInfoClassName}`}>任务 ID：{store.task.id}</h4>;
    }

    /**
     * Hotkeys
     */
    if (enableHotkeys && enableTooltips) {
      buttons.submit = <Hint> [ Ctrl+Enter ]</Hint>;
      buttons.skip = <Hint> [ Ctrl+Space ]</Hint>;
      buttons.update = <Hint> [ Alt+Enter] </Hint>;
    }

    let skipButton;
    let updateButton;
    let submitButton;
    let draftMenu;

    /**
     * Check for Predict Menu
     */
    // Manager roles that can force-skip unskippable tasks (OW=Owner, AD=Admin, MA=Manager)
    const MANAGER_ROLES = ["OW", "AD", "MA"];

    if (!store.annotationStore.predictSelect || store.explore) {
      const disabled = store.isSubmitting;
      const task = store.task;
      const isEnterprise = window.APP_SETTINGS?.billing?.enterprise;
      const skipDisabled = isEnterprise ? task?.allow_skip === false : false;
      const userRole = window.APP_SETTINGS?.user?.role;
      const hasForceSkipPermission = MANAGER_ROLES.includes(userRole);
      const canSkip = !skipDisabled || hasForceSkipPermission;
      const skipButtonDisabled = disabled || !canSkip;

      const skipTooltip = canSkip ? "取消（跳过）任务：[ Ctrl+Space ]" : "此任务无法跳过";

      const showInfoIcon = skipButtonDisabled && hasForceSkipPermission;

      if (store.hasInterface("skip")) {
        skipButton = (
          <>
            {showInfoIcon && (
              <Tooltip title="标注员和审核员将无法跳过此任务">
                <IconInfoOutline width={20} height={20} className="text-neutral-content ml-auto cursor-pointer" />
              </Tooltip>
            )}
            <Button
              disabled={skipButtonDisabled}
              look="danger"
              onClick={canSkip ? store.skipTask : undefined}
              tooltip={skipTooltip}
              className={`${styles.skip} ${skipButtonClassName}`}
            >
              Skip {buttons.skip}
            </Button>
          </>
        );
      }

      if ((userGenerate && !sentUserGenerate) || (store.explore && !userGenerate && store.hasInterface("submit"))) {
        submitButton = (
          <Button
            disabled={disabled}
            look="primary"
            icon={<CheckOutlined />}
            onClick={store.submitAnnotation}
            tooltip="保存结果：[ Ctrl+Enter ]"
            className={`${styles.submit} ${submitButtonClassName}`}
          >
            Submit {buttons.submit}
          </Button>
        );
      }

      if ((userGenerate && sentUserGenerate) || (!userGenerate && store.hasInterface("update"))) {
        updateButton = (
          <Button
            disabled={disabled}
            look="primary"
            icon={<CheckCircleOutlined />}
            onClick={store.updateAnnotation}
            tooltip="更新此任务：[ Alt+Enter ]"
            className={updateButtonClassName}
          >
            {sentUserGenerate || versions.result ? "Update" : "Submit"} {buttons.update}
          </Button>
        );
      }

      if (!store.hasInterface("annotations:menu")) {
        draftMenu = <DraftPanel item={item} />;
      }
    }

    const content = (
      <div className={styles.block}>
        <div className={styles.wrapper}>
          <div className={styles.container}>
            {skipButton}
            {updateButton}
            {submitButton}
            {draftMenu}
          </div>
          {taskInformation}
        </div>
      </div>
    );

    return (item.type === "annotation" || store.explore) && content;
  }),
);
