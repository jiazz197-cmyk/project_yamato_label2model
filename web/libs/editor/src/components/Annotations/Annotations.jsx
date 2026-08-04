import { Component } from "react";
import { Badge, Card, List, Popconfirm } from "antd";
import { Button } from "@humansignal/ui";
import { Tooltip } from "@humansignal/ui";
import { observer } from "mobx-react";
import {
  DeleteOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  PlusOutlined,
  StarFilled,
  StarOutlined,
  StopOutlined,
  WindowsOutlined,
} from "@ant-design/icons";

import Utils from "../../utils";
import styles from "./Annotations.module.css";

/** @deprecated this file is not used; DraftPanel is moved to separate component */

export const DraftPanel = observer(({ item }) => {
  if (!item.draftSaved && !item.versions.draft) return null;
  const saved = item.draft && item.draftSaved ? ` saved ${Utils.UDate.prettyDate(item.draftSaved)}` : "";

  if (!item.selected) {
    if (!item.draft) return null;
    return <div>draft{saved}</div>;
  }
  if (!item.versions.result || !item.versions.result.length) {
    return <div>{saved ? `draft${saved}` : "未提交的草稿"}</div>;
  }
  return (
    <div>
      <Button
        look="string"
        onClick={item.toggleDraft}
        tooltip={item.draftSelected ? "切换到已提交的结果" : "切换到当前草稿"}
      >
        {item.draftSelected ? "draft" : "submitted"}
      </Button>
      {saved}
    </div>
  );
});

const Annotation = observer(({ item, store }) => {
  const removeHoney = () => (
    <Button
      size="small"
      tooltip="取消将此结果设为基准答案"
      onClick={(ev) => {
        ev.preventDefault();
        item.setGroundTruth(false);
      }}
      aria-label="取消基准答案"
    >
      <StarOutlined />
    </Button>
  );

  const setHoney = () => {
    const title = item.ground_truth ? "取消将此结果设为基准答案" : "将此结果设为基准答案";

    return (
      <Button
        size="small"
        look="string"
        tooltip={title}
        onClick={(ev) => {
          ev.preventDefault();
          item.setGroundTruth(!item.ground_truth);
        }}
        aria-label={item.ground_truth ? "取消基准答案" : "设为基准答案"}
      >
        {item.ground_truth ? <StarFilled /> : <StarOutlined />}
      </Button>
    );
  };

  const toggleVisibility = (e) => {
    e.preventDefault();
    e.stopPropagation();
    item.toggleVisibility();
    const c = document.getElementById(`c-${item.id}`);

    if (c) c.style.display = item.hidden ? "none" : "unset";
  };

  const highlight = () => {
    const c = document.getElementById(`c-${item.id}`);

    if (c) c.classList.add("hover");
  };

  const unhighlight = () => {
    const c = document.getElementById(`c-${item.id}`);

    if (c) c.classList.remove("hover");
  };

  /**
   * Default badge for saved annotations
   */
  let badge = <Badge status="default" />;

  /**
   *
   */
  let annotationID;

  /**
   * Title of card
   */
  if (item.userGenerate && !item.sentUserGenerate) {
    annotationID = <span className={styles.title}>未保存的标注</span>;
  } else {
    if (item.pk) {
      annotationID = <span className={styles.title}>ID {item.pk}</span>;
    } else if (item.id) {
      annotationID = <span className={styles.title}>ID {item.id}</span>;
    }
  }

  /**
   * Badge for processing of user generate annotation
   */
  if (item.userGenerate) {
    badge = <Badge status="processing" />;
  }

  /**
   * Badge for complete of user generate annotation
   */
  if (item.userGenerate && item.sentUserGenerate) {
    badge = <Badge status="success" />;
  }

  const btnsView = () => {
    const confirm = () => {
      // ev.preventDefault();
      // debugger;
      item.list.deleteAnnotation(item);
    };

    return (
      <div className={styles.buttons}>
        {store.hasInterface("ground-truth") && (item.ground_truth ? removeHoney() : setHoney())}
        &nbsp;
        {store.hasInterface("annotations:delete") && (
          <Tooltip placement="topLeft" title="删除所选标注">
            <Popconfirm
              placement="bottomLeft"
              title={"Please confirm you want to delete this annotation"}
              onConfirm={confirm}
              okText="删除"
              okType="danger"
              cancelText="取消"
            >
              <Button size="small" look="string" variant="negative" aria-label="删除所选标注">
                <DeleteOutlined />
              </Button>
            </Popconfirm>
          </Tooltip>
        )}
      </div>
    );
  };

  return (
    <List.Item
      key={item.id}
      className={item.selected ? `${styles.annotation} ${styles.annotation_selected}` : styles.annotation}
      onClick={() => {
        !item.selected && store.annotationStore.selectAnnotation(item.id);
      }}
      onMouseEnter={highlight}
      onMouseLeave={unhighlight}
    >
      <div className={styles.annotationcard}>
        <div>
          <div className={styles.title}>
            {badge}
            {annotationID}
          </div>
          {item.pk ? "Created" : "Started"}
          <i>{item.createdAgo ? ` ${item.createdAgo} ago` : ` ${Utils.UDate.prettyDate(item.createdDate)}`}</i>
          {item.createdBy && item.pk ? ` by ${item.createdBy}` : null}
          <DraftPanel item={item} />
        </div>
        {/* platform uses was_cancelled so check both */}
        {store.hasInterface("skip") && (item.skipped || item.was_cancelled) && (
          <Tooltip alignment="top-left" title="已跳过的标注">
            <StopOutlined className={styles.skipped} />
          </Tooltip>
        )}
        {store.annotationStore.viewingAll && (
          <Button
            size="small"
            look="outlined"
            onClick={toggleVisibility}
            aria-label="切换当前标注的可见性"
          >
            {item.hidden ? <EyeInvisibleOutlined /> : <EyeOutlined />}
          </Button>
        )}
        {item.selected && btnsView()}
      </div>
    </List.Item>
  );
});

class Annotations extends Component {
  render() {
    const { store } = this.props;

    const title = (
      <div className={`${styles.title} ${styles.titlespace}`}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <h3>标注</h3>
        </div>

        <div style={{ marginRight: "1px" }}>
          {store.hasInterface("annotations:add-new") && (
            <Button
              size="small"
              tooltip="创建新标注"
              onClick={(ev) => {
                ev.preventDefault();
                const c = store.annotationStore.createAnnotation();

                store.annotationStore.selectAnnotation(c.id);
              }}
              aria-label="创建新标注"
            >
              <PlusOutlined />
            </Button>
          )}
          &nbsp;
          <Button
            size="small"
            tooltip="查看所有标注"
            look={store.annotationStore.viewingAll ? "filled" : "outlined"}
            onClick={(ev) => {
              ev.preventDefault();
              store.annotationStore.toggleViewingAllAnnotations();
            }}
            aria-label="切换所有标注的显示"
          >
            <WindowsOutlined />
          </Button>
        </div>
      </div>
    );

    const content = store.annotationStore.annotations.map((c) => <Annotation key={c.id} item={c} store={store} />);

    return (
      <Card title={title} size="small" bodyStyle={{ padding: "0", paddingTop: "1px" }}>
        <List>{store.annotationStore.annotations ? content : <p>尚未提交标注</p>}</List>
      </Card>
    );
  }
}

export default observer(Annotations);
