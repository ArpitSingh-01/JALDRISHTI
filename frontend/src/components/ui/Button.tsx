import React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  href?: string;
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size = "md",
      href,
      isLoading = false,
      disabled,
      children,
      leftIcon,
      rightIcon,
      ...props
    },
    ref
  ) => {
    const classNames = cn(
      "btn",
      `btn-${variant}`,
      `btn-${size}`,
      isLoading && "btn-loading",
      className
    );

    const content = (
      <>
        {isLoading && <span className="btn-spinner" aria-hidden="true" />}
        {!isLoading && leftIcon && <span className="btn-icon-left">{leftIcon}</span>}
        <span className="btn-text">{children}</span>
        {!isLoading && rightIcon && <span className="btn-icon-right">{rightIcon}</span>}
      </>
    );

    if (href && !disabled && !isLoading) {
      return (
        <Link href={href} className={classNames}>
          {content}
        </Link>
      );
    }

    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={classNames}
        {...props}
      >
        {content}
      </button>
    );
  }
);

Button.displayName = "Button";
