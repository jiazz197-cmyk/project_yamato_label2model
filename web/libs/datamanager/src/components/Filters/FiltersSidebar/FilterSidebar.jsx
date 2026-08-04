import { inject } from "mobx-react";
import { IconChevronLeft } from "@humansignal/icons";
import { cn } from "../../../utils/bem";
import { Button } from "@humansignal/ui";
import { Filters } from "../Filters";
import "./FilterSidebar.prefix.css";

const sidebarInjector = inject(({ store }) => {
  const viewsStore = store.viewsStore;

  return {
    viewsStore,
    sidebarEnabled: viewsStore?.sidebarEnabled,
    sidebarVisible: viewsStore?.sidebarVisible,
  };
});

export const FiltersSidebar = sidebarInjector(({ viewsStore, sidebarEnabled, sidebarVisible }) => {
  return sidebarEnabled && sidebarVisible ? (
    <div className={cn("filters-sidebar").toClassName()}>
      <div className={cn("filters-sidebar").elem("header").toClassName()}>
        <div className={cn("filters-sidebar").elem("extra").toClassName()}>
          <Button
            look="string"
            onClick={() => viewsStore.collapseFilters()}
            tooltip="取消固定筛选"
            aria-label="取消固定筛选"
          >
            <IconChevronLeft width={24} height={24} />
          </Button>
          <div className={cn("filters-sidebar").elem("title").toClassName()}>筛选</div>
        </div>
      </div>
      <Filters sidebar={true} />
    </div>
  ) : null;
});
FiltersSidebar.displayName = "FiltersSidebar";
