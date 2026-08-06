import localFilesProvider from "./localFiles";
import redisProvider from "./redis";

export const providers = {
  redis: redisProvider,
  // Local provider
  localfiles: localFilesProvider,
};
