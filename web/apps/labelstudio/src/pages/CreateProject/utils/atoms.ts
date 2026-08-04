import { isDefined } from "@humansignal/core/lib/utils/helpers";
import { API } from "apps/labelstudio/src/providers/ApiProvider";
import { projectAtom } from "apps/labelstudio/src/providers/ProjectProvider";
import { atomWithQuery } from "jotai-tanstack-query";

export const sampleDatasetAtom = atomWithQuery((get) => {
  const project = get(projectAtom);
  const labelConfig = project?.label_config;
  return {
    queryKey: [labelConfig, project, "sample-data"],
    enabled: isDefined(labelConfig) && labelConfig !== "<View></View>",
    async queryFn() {
      const response = await API.invoke(
        "createSampleTask",
        { pk: project.id },
        {
          body: {
            label_config: project?.label_config ?? "<View></View>",
            include_annotation_and_prediction: true,
          },
        },
      );

      if (!response?.$meta?.ok) {
        return JSON.stringify({ error: "无法准备示例数据。" }, null, "  ");
      }

      if (!response?.sample_task) {
        return JSON.stringify({ error: "没有可用的示例任务数据。" }, null, "  ");
      }

      return JSON.stringify(response.sample_task, null, "  ");
    },
  };
});
