import { EnterpriseBadge, IconSpark } from "@humansignal/ui";
import { Alert, AlertTitle, AlertDescription } from "@humansignal/shad/components/ui/alert";
import { IconCloudProviderDatabricks } from "@humansignal/icons";
import type { ProviderConfig } from "@humansignal/app-common/blocks/StorageProviderForm/types/provider";

const databricksProvider: ProviderConfig = {
  name: "databricks",
  title: "Databricks Files\n(UC Volumes)",
  description: "使用所有必需的设置配置 Databricks Unity Catalog Volumes 连接（仅代理模式）",
  icon: IconCloudProviderDatabricks,
  disabled: true,
  badge: <EnterpriseBadge />,
  fields: [
    {
      name: "enterprise_info",
      type: "message",
      content: (
        <Alert variant="gradient">
          <IconSpark />
          <AlertTitle>企业版功能</AlertTitle>
          <AlertDescription>
            Databricks Files (UC Volumes) is available in Yamato Enterprise.{" "}
            <a
              href="https://docs.humansignal.com/guide/storage.html#Databricks-Files-UC-Volumes"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:no-underline"
            >
              了解更多
            </a>
          </AlertDescription>
        </Alert>
      ),
    },
  ],
  layout: [{ fields: ["enterprise_info"] }],
};

export default databricksProvider;
