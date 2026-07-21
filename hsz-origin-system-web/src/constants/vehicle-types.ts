export const vehicleTypeLabels: Record<string, string> = {
  "1": "一型客车",
  "2": "二型客车",
  "3": "三型客车",
  "4": "四型客车",
  "11": "一型货车",
  "12": "二型货车",
  "13": "三型货车",
  "14": "四型货车",
  "15": "五型货车",
  "16": "六型货车",
  "21": "一型专项作业车",
  "22": "二型专项作业车",
  "23": "三型专项作业车",
  "24": "四型专项作业车",
  "25": "五型专项作业车",
  "26": "六型专项作业车",
};
export const formatVehicleType = (code: string) =>
  vehicleTypeLabels[code] ?? `车型代码 ${code}`;
