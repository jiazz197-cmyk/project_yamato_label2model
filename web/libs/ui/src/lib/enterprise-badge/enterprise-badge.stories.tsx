import type { Meta, StoryObj } from "@storybook/react";
import { EnterpriseBadge } from "./enterprise-badge";

const meta: Meta<typeof EnterpriseBadge> = {
  component: EnterpriseBadge,
  title: "UI/EnterpriseBadge",
  argTypes: {
    style: {
      control: "select",
      options: ["filled", "outline", "ghost", "solid"],
    },
    shape: {
      control: "select",
      options: ["rounded", "square"],
    },
    size: {
      control: "select",
      options: ["medium", "small"],
    },
  },
};

export default meta;
type Story = StoryObj<typeof EnterpriseBadge>;

export const Default: Story = {
  args: {},
};

export const WithLabel: Story = {
  args: {
    children: "企业版",
    style: "filled",
  },
};

export const Ghost: Story = {
  args: {
    children: "企业版",
    style: "ghost",
  },
};

export const Outline: Story = {
  args: {
    children: "企业版",
    style: "outline",
  },
};

export const Solid: Story = {
  args: {
    children: "企业版",
    style: "solid",
  },
};

export const IconOnlyAndGhost: Story = {
  args: {
    children: "",
    style: "ghost",
  },
};

export const Small: Story = {
  args: {
    children: "企业版",
    size: "small",
  },
};

export const IconOnlySmall: Story = {
  args: {
    children: "",
    size: "small",
  },
};

export const Rounded: Story = {
  args: {
    children: "企业版",
    shape: "rounded",
  },
};

export const CustomLabel: Story = {
  args: {
    children: "Custom label",
    icon: null,
  },
};

export const AllStyles: Story = {
  render: () => (
    <div className="flex flex-wrap gap-3 items-center">
      <EnterpriseBadge>企业版</EnterpriseBadge>
      <EnterpriseBadge style="outline">企业版</EnterpriseBadge>
      <EnterpriseBadge style="ghost">企业版</EnterpriseBadge>
      <EnterpriseBadge style="solid">企业版</EnterpriseBadge>
    </div>
  ),
};
