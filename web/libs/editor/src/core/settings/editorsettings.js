export default {
  enableHotkeys: {
    newUI: {
      title: "标注快捷键",
      description: "启用后可使用快捷键快速选择标签",
    },
    description: "启用标注快捷键",
    onChangeEvent: "toggleHotkeys",
    defaultValue: true,
  },
  enableTooltips: {
    newUI: {
      title: "在提示中显示快捷键",
      description: "在工具和操作的提示中显示快捷键",
    },
    description: "显示快捷键提示",
    onChangeEvent: "toggleTooltips",
    checked: "",
    defaultValue: false,
  },
  enableLabelTooltips: {
    newUI: {
      title: "在标签上显示快捷键",
      description: "在标签上显示快捷键",
    },
    description: "显示标签快捷键提示",
    onChangeEvent: "toggleLabelTooltips",
    defaultValue: true,
  },
  showLabels: {
    newUI: {
      title: "显示区域标签",
      description: "显示区域标签名称",
    },
    description: "在区域内显示标签",
    onChangeEvent: "toggleShowLabels",
    defaultValue: false,
  },
  continuousLabeling: {
    newUI: {
      title: "创建区域后保持标签选中",
      description: "允许使用所选标签连续创建区域",
    },
    description: "创建区域后保持标签选中",
    onChangeEvent: "toggleContinuousLabeling",
    defaultValue: false,
  },
  selectAfterCreate: {
    newUI: {
      title: "创建区域后选中它",
      description: "自动选中新建的区域",
    },
    description: "创建后选中区域",
    onChangeEvent: "toggleSelectAfterCreate",
    defaultValue: false,
  },
  showLineNumbers: {
    newUI: {
      tags: "文本标签",
      title: "显示行号",
      description: "识别并引用文档中的特定文本行",
    },
    description: "为文本显示行号",
    onChangeEvent: "toggleShowLineNumbers",
    defaultValue: false,
  },
  preserveSelectedTool: {
    newUI: {
      tags: "图像标签",
      title: "保持所选工具",
      description: "在任务之间保留所选工具",
    },
    description: "记住所选工具",
    onChangeEvent: "togglepreserveSelectedTool",
    defaultValue: true,
  },
  enableSmoothing: {
    newUI: {
      tags: "图像标签",
      title: "缩放时像素平滑",
      description: "放大时平滑图像像素",
    },
    description: "缩放时启用图像平滑",
    onChangeEvent: "toggleSmoothing",
    defaultValue: true,
  },
  invertedZoom: {
    newUI: {
      tags: "图像标签",
      title: "反转缩放方向",
      description: "反转滚动缩放的缩放方向",
    },
    description: "启用反转缩放方向",
    onChangeEvent: "toggleInvertedZoom",
    defaultValue: false,
  },
};
