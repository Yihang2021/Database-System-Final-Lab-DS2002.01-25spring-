CREATE DATABASE IF NOT EXISTS personnel_system
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;

USE personnel_system;

CREATE TABLE Department (
    dept_id VARCHAR(20) PRIMARY KEY,
    dept_name VARCHAR(50) UNIQUE NOT NULL,
    manager_id VARCHAR(10),  
    function_desc TEXT,
    phone VARCHAR(20)
);

CREATE TABLE `Position` ( 
    pos_id VARCHAR(10) PRIMARY KEY,
    pos_name VARCHAR(50) NOT NULL,
    dept_id VARCHAR(20) NOT NULL,
    min_salary DECIMAL(10,2) NOT NULL,
    max_salary DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (dept_id) REFERENCES Department(dept_id),
    CHECK (min_salary <= max_salary)
);

CREATE TABLE Employee (
    emp_id VARCHAR(10) PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    gender ENUM('男', '女') NOT NULL,
    education ENUM('中专', '高中', '大专', '本科', '硕士', '博士') NOT NULL,
    phone VARCHAR(20),
    email VARCHAR(100),
    pos_id VARCHAR(10) NOT NULL,
    salary DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (pos_id) REFERENCES `Position`(pos_id)
);

ALTER TABLE Department
ADD CONSTRAINT fk_manager
FOREIGN KEY (manager_id) REFERENCES Employee(emp_id) ON DELETE SET NULL;

CREATE TABLE SystemUser (
    user_id VARCHAR(20) PRIMARY KEY COMMENT '用户ID',
    username VARCHAR(50) UNIQUE NOT NULL COMMENT '用户名',
    password_hash VARCHAR(60) NOT NULL COMMENT 'bcrypt加密密码',
    role ENUM('员工', '领导') NOT NULL DEFAULT '员工',
    emp_id VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    last_password_change TIMESTAMP COMMENT '最后修改时间',
    FOREIGN KEY (emp_id) REFERENCES employee(emp_id)
);

CREATE TABLE PositionChange (
    change_id INT AUTO_INCREMENT PRIMARY KEY,
    emp_id VARCHAR(10) NOT NULL,
    change_date DATETIME NOT NULL,
    old_pos_id VARCHAR(10) NOT NULL,
    new_pos_id VARCHAR(10) NOT NULL,
    old_salary DECIMAL(10,2) NOT NULL,
    new_salary DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (emp_id) REFERENCES Employee(emp_id),
    FOREIGN KEY (old_pos_id) REFERENCES `Position`(pos_id),
    FOREIGN KEY (new_pos_id) REFERENCES `Position`(pos_id)
);

CREATE TABLE Attendance (
    attendance_id INT AUTO_INCREMENT PRIMARY KEY,
    emp_id VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    FOREIGN KEY (emp_id) REFERENCES Employee(emp_id),
    UNIQUE (emp_id, date)
);

CREATE TABLE LeaveRequest (
    leave_id INT AUTO_INCREMENT PRIMARY KEY,
    emp_id VARCHAR(10) NOT NULL,
    leave_type VARCHAR(50) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    request_time DATETIME NOT NULL,
    status ENUM('待审批', '已批准', '已拒绝') DEFAULT '待审批',
    FOREIGN KEY (emp_id) REFERENCES Employee(emp_id),
    CHECK (end_date > start_date)
);

DELIMITER $$

-- 在插入positionchange记录前校验薪资范围
CREATE TRIGGER BeforePositionChangeInsert 
BEFORE INSERT ON PositionChange
FOR EACH ROW
BEGIN
    DECLARE target_min DECIMAL(10,2);
    DECLARE target_max DECIMAL(10,2);
    DECLARE is_department_manager BOOLEAN;

    -- 获取目标岗位的薪资范围
    SELECT min_salary, max_salary INTO target_min, target_max
    FROM `Position`
    WHERE pos_id = NEW.new_pos_id;

    -- 检查新薪资是否在目标岗位范围内
    IF NEW.new_salary < target_min OR NEW.new_salary > target_max THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = '薪资超出目标岗位范围';
    END IF;

    -- 检查员工是否是部门负责人
    SELECT COUNT(*) INTO is_department_manager
    FROM Department
    WHERE manager_id = NEW.emp_id;

    IF is_department_manager > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = '部门负责人禁止修改岗位';
    END IF;
END$$

DELIMITER ;

DELIMITER $$

-- 在positionchange插入成功后更新employee表
CREATE TRIGGER AfterPositionChangeInsert 
AFTER INSERT ON PositionChange
FOR EACH ROW
BEGIN
    -- 更新员工表
    UPDATE Employee
    SET 
        pos_id = NEW.new_pos_id,
        salary = NEW.new_salary
    WHERE emp_id = NEW.emp_id;
END$$

DELIMITER ;

DELIMITER $$

CREATE TRIGGER before_department_update 
BEFORE UPDATE ON department
FOR EACH ROW
BEGIN
    DECLARE employee_dept_id VARCHAR(10);
    
    -- 仅当设置新的负责人时触发检查
    IF NEW.manager_id IS NOT NULL THEN
        -- 获取该员工所属部门
        SELECT p.dept_id INTO employee_dept_id
        FROM employee e
        JOIN position p ON e.pos_id = p.pos_id
        WHERE e.emp_id = NEW.manager_id;
        
        -- 检查员工是否存在
        IF employee_dept_id IS NULL THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '错误：指定的负责人不存在于员工表中';
        END IF;
        
        -- 检查部门匹配性
        IF employee_dept_id != NEW.dept_id THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '错误：负责人必须属于本部门';
        END IF;
    END IF;
END$$

DELIMITER ;

-- 部门ID使用英文缩写，便于识别
INSERT INTO department (dept_id, dept_name, function_desc, phone) VALUES
('TECH', '技术部', '软件开发与系统维护', '010-12345678'),
('MKT', '市场部', '品牌推广与客户管理', '021-98765432'),
('HR', '人力资源部', '员工招聘与培训', '0755-87654321'),
('FIN', '财务部', '资金管理与审计', '028-55667788'),
('ADMIN', '行政部', '后勤支持与资产管理', '020-33445566'),
('RD', '研发部', '前沿技术预研', '027-11223344');

-- 岗位ID格式：部门缩写+3位序号（如TECH001）
INSERT INTO position (pos_id, pos_name, dept_id, min_salary, max_salary) VALUES
-- 技术部岗位
('TECH001', 'Java高级工程师', 'TECH', 15000.00, 30000.00),
('TECH002', '前端开发工程师', 'TECH', 12000.00, 25000.00),
('TECH003', '架构师', 'TECH', 35000.00, 60000.00),
-- 市场部岗位
('MKT001', '市场总监', 'MKT', 25000.00, 50000.00),
('MKT002', '品牌经理', 'MKT', 15000.00, 30000.00),
-- 人力资源部岗位
('HR001', 'HRBP', 'HR', 10000.00, 20000.00),
-- 财务部岗位
('FIN001', '财务经理', 'FIN', 20000.00, 40000.00),
-- 行政部岗位
('ADMIN001', '行政主管', 'ADMIN', 8000.00, 15000.00),
-- 研发部岗位
('RD001', 'AI算法工程师', 'RD', 30000.00, 80000.00),
('RD002', '区块链研究员', 'RD', 25000.00, 60000.00);

-- 员工ID格式：EMP+3位序号
-- 薪资需在岗位范围内
INSERT INTO employee (emp_id, name, gender, education, phone, email, pos_id, salary) VALUES
-- 技术部员工
('EMP001', '邢祎航', '男', '硕士', '13800138001', 'xingyh@company.com', 'TECH001', 28000.00),
('EMP002', '莫亦非', '女', '本科', '13900139002', 'moyf@company.com', 'TECH002', 18000.00),
('EMP003', '王强', '男', '博士', '13600136003', 'wangqiang@company.com', 'TECH003', 55000.00),
-- 市场部员工
('EMP004', '陈静', '女', '硕士', '13500135004', 'chenjing@company.com', 'MKT001', 45000.00),
('EMP005', '赵敏', '女', '本科', '13700137005', 'zhaomin@company.com', 'MKT002', 20000.00),
-- 人力资源部员工
('EMP006', '刘洋', '男', '本科', '13400134006', 'liuyang@company.com', 'HR001', 15000.00),
-- 财务部员工
('EMP007', '周杰', '男', '硕士', '13300133007', 'zhoujie@company.com', 'FIN001', 35000.00),
-- 行政部员工
('EMP008', '吴婷', '女', '大专', '13200132008', 'wuting@company.com', 'ADMIN001', 12000.00),
-- 研发部员工
('EMP009', '林浩', '男', '博士', '13100131009', 'linhao@company.com', 'RD001', 75000.00),
('EMP010', '徐菲', '女', '硕士', '13000130010', 'xufei@company.com', 'RD002', 40000.00),
('EMP011', '郑浩', '男', '本科', '15900159011', 'zhenghao@company.com', 'TECH001', 16000.00),
('EMP012', '黄薇', '女', '硕士', '15800158012', 'huangwei@company.com', 'MKT001', 30000.00),
('EMP013', '高磊', '男', '本科', '15700157013', 'gaolei@company.com', 'TECH002', 22000.00),
('EMP014', '程琳', '女', '博士', '15600156014', 'chenglin@company.com', 'RD001', 80000.00),
('EMP015', '韩雪', '女', '硕士', '15500155015', 'hanxue@company.com', 'HR001', 18000.00);

-- 密码统一为123456（bcrypt加密值）
INSERT INTO systemuser (user_id, username, password_hash, role, emp_id) VALUES
('U001', 'xingyihang', '$2b$12$rpCA8Lc0lzminj4qbxE8Cev0oclP/wH6VfiBKqkCTC/t6xK3ffaLm', '领导', 'EMP001'),
('U002', 'moyifei', '$2b$12$HfACHQUV9Ym7OqpJ6n1KdeMmke/b5NNqwYObMU8GEyAGiroCx/Muq', '员工', 'EMP002'),
('U003', 'wangqiang', '$2b$12$grq3sgb8MUS2vtQGFo8KoeXOZeNiCmoWVVztQep..Ei6pPjVqoDh2', '领导', 'EMP003'),
('U004', 'chenjing', '$2b$12$.amNnOxHlD1Sy6U66vu5COVTQVYpmj6h9tPH2d8KmYEaaEJiClgZa', '领导', 'EMP004'),
('U005', 'zhaomin', '$2b$12$C0v7.ivA8V.jQbHx61bo.ORHna6b5b.4adIDBTinG.nhrfypdRAAG', '员工', 'EMP005'),
('U006', 'liuyang', '$2b$12$fKT6Qs7q7G90Izd9Jhqe5uG5dQsPpdQp8o8feoqKxYKS/1syt350G', '员工', 'EMP006'),
('U007', 'zhoujie', '$2b$12$fT0S9GKUmnoP64Y/LnZz1O8b0XBBDvguMZhaaIZSG1Mw3GzQkwrDm', '领导', 'EMP007'),
('U008', 'wuting', '$2b$12$FjCa9eTzfR3bUduflIdIi.7xTHcS4m3VJQbxU45TfvWtUViZIk3jy', '员工', 'EMP008'),
('U009', 'linhao', '$2b$12$RAa5qMXzgtCSt1vO8XoIs.JFoIwl5McRT3tiwDRvG8X7F4heJwKkm', '领导', 'EMP009'),
('U010', 'xufei', '$2b$12$bPWwkuqF1snQWeP.Adpf6eQuOqQJ5PnrYFJ5Eh/yXeFiQH/fJDliG', '员工', 'EMP010');

-- 每个部门指定一名负责人（需确保该员工属于该部门）
UPDATE department SET manager_id = 'EMP001' WHERE dept_id = 'TECH';  -- 技术部负责人
UPDATE department SET manager_id = 'EMP004' WHERE dept_id = 'MKT';   -- 市场部负责人
UPDATE department SET manager_id = 'EMP006' WHERE dept_id = 'HR';    -- 人力资源部负责人
UPDATE department SET manager_id = 'EMP007' WHERE dept_id = 'FIN';   -- 财务部负责人
UPDATE department SET manager_id = 'EMP008' WHERE dept_id = 'ADMIN'; -- 行政部负责人
UPDATE department SET manager_id = 'EMP009' WHERE dept_id = 'RD';    -- 研发部负责人


ALTER TABLE LeaveRequest
ADD COLUMN reason TEXT AFTER request_time,
ADD COLUMN reviewer_id VARCHAR(10),
ADD COLUMN review_time DATETIME,
ADD FOREIGN KEY (reviewer_id) REFERENCES employee(emp_id);




