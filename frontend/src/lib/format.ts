const currencyFormatter = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

const numberFormatter = new Intl.NumberFormat('en-IN')

export function formatCurrency(value: number): string {
  return currencyFormatter.format(value)
}

export function formatNumber(value: number): string {
  return numberFormatter.format(value)
}

export function formatCompactCurrency(value: number): string {
  if (Math.abs(value) >= 10000000) {
    return `₹${(value / 10000000).toFixed(1)}Cr`
  }

  if (Math.abs(value) >= 100000) {
    return `₹${(value / 100000).toFixed(1)}L`
  }

  if (Math.abs(value) >= 1000) {
    return `₹${(value / 1000).toFixed(1)}k`
  }

  return `₹${value}`
}

export function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00`)

  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(date)
}

export function formatShortDate(value: string): string {
  const date = new Date(`${value}T00:00:00`)

  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat('en-IN', {
    day: '2-digit',
    month: 'short',
  }).format(date)
}

export function formatPercent(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`
}
