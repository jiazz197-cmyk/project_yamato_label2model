export const recipes = [
  {
    title: "目标框检测",
    type: "community",
    group: "计算机视觉",
    image: "bbox.png",
    details: `<h1>简单目标检测</h1>
    <p>使用边界框标注的示例配置</p>
    <p>你可以配置标签及其颜色</p>`,
    config: `<View>
  <Image name="image" value="$image"/>
  <RectangleLabels name="label" toName="image">
    <Label value="Airplane" background="green"/>
    <Label value="Car" background="blue"/>
  </RectangleLabels>
</View>`,
  },
  {
    title: "多边形标注",
    type: "community",
    group: "计算机视觉",
    image: "polygon.png",
    details: "",
    config: `<View>
  <Header value="选择标签后点击图像开始"/>
  <Image name="image" value="$image"/>
  <PolygonLabels name="label" toName="image"
                 strokeWidth="3" pointSize="small"
                 opacity="0.9">
    <Label value="Airplane" background="red"/>
    <Label value="Car" background="blue"/>
  </PolygonLabels>
</View>
`,
  },
  {
    title: "命名实体识别",
    type: "community",
    group: "NLP",
    image: "text.png",
    config: `<View>
  <Labels name="label" toName="text">
    <Label value="Person" background="red"/>
    <Label value="Organization" background="darkorange"/>
    <Label value="Fact" background="orange"/>
    <Label value="Money" background="green"/>
    <Label value="Date" background="darkblue"/>
    <Label value="Time" background="blue"/>
    <Label value="Ordinal" background="purple"/>
    <Label value="Percent" background="#842"/>
    <Label value="Product" background="#428"/>
    <Label value="Language" background="#482"/>
    <Label value="Location" background="rgba(0,0,0,0.8)"/>
  </Labels>

  <Text name="text" value="$text"/>
</View>`,
  },
];
